from typing import List
from langchain_core.documents import Document
from services.rag.chroma_retriever import VectorStoreManager
from services.rag.bm25_retriever import BM25Manager
import chromadb


class RetrievalService:
    """
    Handles hybrid retrieval (Dense + Sparse) with parent-child expansion and image-only slide navigation.
    It will be the intermediary between the RAG pipeline and the vector store.
    """
    def __init__(self, vector_store_manager: VectorStoreManager, bm25_manager: BM25Manager = None, 
                 db_path: str = "CourseLens_data/chroma_db", 
                 collection_name: str = "course_lens", k: int = 5, parent_swap_threshold: int = 2, search_type : str = "similarity"):
        self.vector_store_manager = vector_store_manager
        self.bm25_manager = bm25_manager
        self.k = k
        self.parent_swap_threshold = parent_swap_threshold
        self.search_type = search_type
        
        # Connectikng to chroma db to fetch meta data for chunks
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_collection(collection_name)
    
        
    def retrieve(self, query: str, lecture_number: int = None, k: int = None, disable_swapping: bool = False) -> List[Document]:
        """
        Retrieve documents on the basis of query similarity, and account methods to enrich chunks 
        """
        filter_dict = None
        if lecture_number is not None:
            filter_dict = {"lecture_number": {"$lte": lecture_number}}

        # Use the provided k, or fallback to the instance default k
        search_k = k if k is not None else self.k

        # Step 1: Hybrid Similarity Search (Dense + Sparse Fusion)
        # Increase candidate pool k=50 to ensure narrow matches (like "goals") aren't lost early
        dense_docs = self.vector_store_manager.similarity_search(query, k=50, filter=filter_dict)
        
        if self.bm25_manager:
            sparse_docs = self.bm25_manager.search(query, k=50, filter=filter_dict)
            # RRF fusion — returns list of (Document, score)
            retrieved_docs_with_scores = self._reciprocal_rank_fusion(dense_docs, sparse_docs)
        else:
            # For dense-only, we treat the rank as the score to stay consistent
            # Using 1.0 / (rank + 60) scaled by 0.8
            retrieved_docs_with_scores = [(doc, 0.8 / (i + 60)) for i, doc in enumerate(dense_docs)]
        
        # Step 2: Apply Title-Match Boost (Heuristic for slide-based RAG)
        # Works on the (Document, score) list and returns sorted Documents
        retrieved_docs = self._apply_title_boost(query, retrieved_docs_with_scores)

        # Step 3: Handle image-only slides
        retrieved_docs = self._handle_image_slides(retrieved_docs)

        # Step 4: Parent-Child Swap (Broader Context)
        if not disable_swapping:
            retrieved_docs = self._parent_child_swap(retrieved_docs)

        # Step 5: Deduplicate (keep best version of each slide)
        retrieved_docs = self._deduplicate(retrieved_docs)

        # Step 6: Final Slice (Keeping search_k results)
        retrieved_docs = retrieved_docs[:search_k]

        self._log_retrieved_chunks(retrieved_docs)

        return retrieved_docs

    def _reciprocal_rank_fusion(self, dense_docs: List[Document], sparse_docs: List[Document]) -> List[Document]:
        """Mathematically merges dense conceptual matches with sparse exact keyword matches."""
        fused_scores = {}
        docs_dict = {}
        
        for rank, doc in enumerate(dense_docs):
            # Using getattr(doc, "id") to ensure we use the unique ChromaDB ID
            doc_id = getattr(doc, "id", None) or doc.metadata.get("id") or doc.page_content[:300]
            # Semantic Weight: 0.9
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (0.9 / (rank + 60))
            docs_dict[doc_id] = doc
            
        for rank, doc in enumerate(sparse_docs):
            doc_id = getattr(doc, "id", None) or doc.metadata.get("id") or doc.page_content[:300]
            # BM25 Weight: 0.1
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (0.1 / (rank + 60))
            docs_dict[doc_id] = doc
            
        reranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        # Return list of (Document, score) for further boosting/filtering
        return [(docs_dict[doc_id], score) for doc_id, score in reranked]

    def _apply_title_boost(self, query: str, docs_with_scores: List[tuple], lecture_number: int = None) -> List[Document]:
        """
        Multiplicative boosting: boosts the RRF score based on title keyword matches.
        Allows conceptual matches to stay on top if confidence is high.
        """
        import re
        STOP_WORDS = {"what", "are", "the", "for", "and", "how", "why", "who", "when", "does", "have", "with", "this", "that"}
        query_terms = set(re.findall(r'\b\w{3,}\b', query.lower()))
        query_terms = {t for t in query_terms if t not in STOP_WORDS}

        if not query_terms:
            return [d for d, s in docs_with_scores]

        final_scored = []
        for doc, score in docs_with_scores:
            title = doc.metadata.get("title", "").lower()
            match_count = sum(1 for term in query_terms if term in title)
            
            # Micro-boost: +5% per keyword match (The verified production peak)
            boosted_score = score * (1.0 + (0.05 * match_count))
            final_scored.append((doc, boosted_score))

        # Re-sort by the NEW boosted scores
        final_scored.sort(key=lambda x: x[1], reverse=True)
        return [d for d, s in final_scored]


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
                    metadata=result["metadatas"][0],
                    id=chunk_id
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
        → replace all children with parent chunk at the position of the highest-ranked child.
        Reduces duplicate context passed to model, while preserving search rank.
        """
        from collections import defaultdict
        
        # 1. Count occurrences of each parent_id among the retrieved children
        children_count = defaultdict(int)
        for doc in docs:
            if doc.metadata.get("chunk_type") == "child" and doc.metadata.get("source_type", "") in ["pptx", "pdf_slideshow"]:
                parent_id = doc.metadata.get("parent_id", "")
                if parent_id:
                    children_count[parent_id] += 1

        result = []
        emitted_parents = set()

        # 2. Re-iterate in original sorted order, preserving rank!
        for doc in docs:
            chunk_type = doc.metadata.get("chunk_type")
            doc_id = getattr(doc, "id", None) or doc.metadata.get("id") or doc.page_content[:300]
            
            if chunk_type == "parent":
                if doc_id not in emitted_parents:
                    result.append(doc)
                    emitted_parents.add(doc_id)
            
            elif chunk_type == "child" and doc.metadata.get("source_type", "") in ["pptx", "pdf_slideshow"]:
                parent_id = doc.metadata.get("parent_id", "")
                if parent_id and children_count[parent_id] >= self.parent_swap_threshold:
                    # Enough children exist to trigger a swap. Emitting the parent HERE preserves the rank 
                    # of the highest-scoring child that triggered the swap.
                    if parent_id not in emitted_parents:
                        parent_doc = self._fetch_by_id(parent_id)
                        if parent_doc:
                            result.append(parent_doc)
                            emitted_parents.add(parent_id)
                else:
                    # Not enough children to swap, keep the child slide independently
                    result.append(doc)
            else:
                # Other types (e.g., pdf or web)
                result.append(doc)

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

    def fetch_lecture_for_summary(self, lecture_number: int) -> List[Document]:
        """
        Fetches all chunks matching the lecture number without vector embeddings,
        skipping parent chunks to get full slide level granularity.
        """
        result = self.collection.get(
            where={"lecture_number": lecture_number},
            include=["documents", "metadatas"]
        )
        return self._process_summary_results(result)

    def fetch_lecture_range_for_summary(self, start_lecture: int, end_lecture: int) -> List[Document]:
        """
        Fetches all chunks matching the lecture range [start_lecture, end_lecture].
        """
        # ChromaDB syntax for range queries — using $and with $gte and $lte filters
        result = self.collection.get(
            where={"$and": [
                {"lecture_number": {"$gte": start_lecture}},
                {"lecture_number": {"$lte": end_lecture}}
            ]},
            include=["documents", "metadatas"]
        )
        return self._process_summary_results(result)

    def _process_summary_results(self, result: dict) -> List[Document]:
        """Internal helper to convert Chroma results to sorted Documents."""
        docs = []
        if result and result.get("documents"):
            for doc_content, meta in zip(result["documents"], result["metadatas"]):
                if meta.get("chunk_type") != "parent":
                    docs.append(Document(page_content=doc_content, metadata=meta))
                    
        # Sort by lecture number first, then slide number, to maintain pedagogical flow
        docs.sort(key=lambda x: (x.metadata.get("lecture_number") or 0, x.metadata.get("slide_number") or 0))
        return docs