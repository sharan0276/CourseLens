from typing import List
from langchain_core.documents import Document
from services.rag.chroma_retriever import VectorStoreManager
import chromadb


class RetrievalService:
    """
    Handles retrieval with parent-child expansion and image-only slide navigation (to fetch relevant context).
    It will be the intermediary between the RAG pipeline and the vector store.
    """
    def __init__(self, vector_store_manager: VectorStoreManager, db_path: str = "CourseLens_data/chroma_db", 
                 collection_name: str = "course_lens", k: int = 5, parent_swap_threshold: int = 2, search_type : str = "similarity"):
        self.vector_store_manager = vector_store_manager
        self.k = k
        self.parent_swap_threshold = parent_swap_threshold
        self.search_type = search_type
        
        # Connectikng to chroma db to fetch meta data for chunks
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_collection(collection_name)
    
        
    def retrieve(self, query: str, lecture_number: int = None) -> List[Document]:
        """
        Retrieve documents on the basis of query similarity, and account methods to enrich chunks 
        """
        filter_dict = None
        if lecture_number is not None:
            filter_dict = {"lecture_number": {"$lte": lecture_number}}

        # Step 1  Similarity Search
        retrieved_docs = self.vector_store_manager.similarity_search(query, k=self.k, filter=filter_dict)
        
        # Step 2: Handle image-only slides
        retrieved_docs = self._handle_image_slides(retrieved_docs)

        # Step 3: Parent-Child Swap (Broader Context)
        #retrieved_docs = self._parent_child_swap(retrieved_docs)

        # Step 4: Deduplicate (keep best version of each slide)
        retrieved_docs = self._deduplicate(retrieved_docs)

        self._log_retrieved_chunks(retrieved_docs)

        return retrieved_docs

    

    def _log_retrieved_chunks(self, docs: List[Document]):
        """
        Logs the retrieved chunks for debugging purposes.
        """
        print("\nRetrieved Chunks:")
        for doc in docs:
            chunk_type = doc.metadata.get("chunk_type", "Unknown")
            title = doc.metadata.get("title", "")
            slide = doc.metadata.get("slide_number", "None")
            lecture = doc.metadata.get("lecture_number", "")
            
            only_images = doc.metadata.get("only_images", False)
            source_type = doc.metadata.get("source_type", "")
            source_file = doc.metadata.get("source_file", "")
            
            if chunk_type == "parent":
                print(f"ID: {chunk_type} - title {title} - Lecture {lecture}")
            else:
                base_log = f"ID: {chunk_type} - title {title} - Slide {slide} - Lecture {lecture}"
                if only_images and source_type in ["pptx", "pdf_slideshow"]:
                    base_log += f" - [Image Source: {source_file}]"
                print(base_log)
        print("------------------------\n")

# Image Only Slide Handler - currently will be fetching the next and previous slide to pack some context to the LLM
# This is a temporary solution and will be replaced with a more robust solution in the future

    def _handle_image_slides(self, docs: List[Document]) -> List[Document]:
        """
        If a retrieved chunk is an image-only slide, fetch its parent text chunk for context.
        """
        result = []
        for doc in docs:
            if doc.metadata.get("only_images"):
                neighbors = self._fetch_neighbours(doc)
                neighbors = self._fetch_neighbours(doc)
                result.extend(neighbors)
            else:
                result.append(doc)
        return result
    

    def _fetch_neighbours(self, doc: Document) -> List[Document]:
        """
        Fetches prev and next slide for image-only chunks to provide context to the LLM.
        """
        
        neighbours = []
        prev_id = doc.metadata.get("prev_slide")
        next_id = doc.metadata.get("next_slide")

        for chunk_id in [prev_id, next_id]:
            if chunk_id:
                neighbour = self._fetch_by_id(chunk_id)
                if neighbour:
                    neighbours.append(neighbour)
        
        if neighbours:
            # Add original image-only slide
            neighbours.append(doc)

        else:
            neighbours = [doc]
        
        return neighbours

    def _fetch_by_id(self, chunk_id: str) -> Document | None:
        """
        Fetches a single document by its chunk_id.
        """
        try:
            result = self.collection.get(
                ids=[chunk_id],
                include=["documents", "metadatas"]
            )
            if result["documents"]:
                return Document(
                    page_content=result["documents"][0],
                    metadata=result["metadatas"][0]
                )
        except Exception as e:
            print(f"Error fetching chunk {chunk_id}: {e}")
            pass
        return None
    

# Swapping Parent and Child 

    def _parent_child_swap(self, docs: List[Document]) -> List[Document]:
        """
        Groups child chunks by parent_id.
        If >= parent_swap_threshold children from same parent found
        → replace all children with parent chunk.
        Reduces duplicate context passed to model.
        """
        # separate parents and children
        parents = [d for d in docs if d.metadata.get("chunk_type") == "parent"]
        children = [d for d in docs if d.metadata.get("chunk_type") == "child"]

        result = list(parents)  # keep any directly retrieved parents
        swapped_parent_ids = set(d.metadata.get("parent_id", "") for d in parents)

        # group children by parent_id, but only for allowed source types
        from collections import defaultdict
        children_by_parent = defaultdict(list)
        for child in children:
            source_type = child.metadata.get("source_type", "")
            if source_type in ["pptx", "pdf_slideshow"]:
                parent_id = child.metadata.get("parent_id", "")
                if parent_id:
                    children_by_parent[parent_id].append(child)
            else:
                # If not eligible for swap, just keep it directly in the results
                result.append(child)

        for parent_id, child_group in children_by_parent.items():
            if len(child_group) >= self.parent_swap_threshold:
                # swap children with parent — only if parent not already in results
                if parent_id not in swapped_parent_ids:
                    parent_doc = self._fetch_by_id(parent_id)
                    if parent_doc:
                        result.append(parent_doc)
                        swapped_parent_ids.add(parent_id)
            else:
                # keep individual children — not enough to warrant swap
                result.extend(child_group)

        return result

# Duplication removal
     
    def _deduplicate(self, docs: List[Document]) -> List[Document]:
        """Removes duplicate documents by content."""
        seen = set()
        unique = []
        for doc in docs:
            content_key = doc.page_content[:300]  # first 300 chars as key to ensure that duplicates are removed
            if content_key not in seen:
                seen.add(content_key)
                unique.append(doc)
        return unique