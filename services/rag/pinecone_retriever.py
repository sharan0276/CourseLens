import os
from typing import List
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore


class VectorStoreManager:
    """ Read-only interface to Pinecone for LangChain RAG pipeline.
    Connects to existing cloud index built by run_ingestion.py"""

    def __init__(self, embeddings_model: Embeddings, persist_directory: str = None, collection_name: str = None):
        from dotenv import load_dotenv
        load_dotenv()
        
        self.embeddings = embeddings_model
        
        index_name = os.getenv("PINECONE_INDEX_NAME", "courselens")
        
        # Initialize Pinecone via LangChain
        self.vector_store = PineconeVectorStore(
            index_name=index_name,
            embedding=self.embeddings,
            pinecone_api_key=os.getenv("PINECONE_API_KEY")
        )
        self._bm25_retriever = None
        print(f"Connected to Pinecone Cloud Index: {index_name}")

    def _get_bm25(self):
        """Self-healing BM25 Loader - Downloads from S3 if missing locally"""
        if self._bm25_retriever is not None:
            return self._bm25_retriever
            
        import os, pickle
        from services.s3_service import S3Service
        
        pkl_path = "CourseLens_data/bm25_retriever.pkl"
        
        if not os.path.exists(pkl_path):
            print("[VectorStoreManager] local BM25 index not found. Fetching from S3...")
            try:
                s3_bucket = os.getenv("S3_BUCKET_NAME", "courselens-data-bucket-test-01")
                s3_service = S3Service(bucket_name=s3_bucket)
                s3_service.download_file("CourseLens_data/bm25_retriever.pkl", pkl_path)
            except Exception as e:
                print(f"[VectorStoreManager] Failed to fetch BM25 from S3: {e}")
                
        if os.path.exists(pkl_path):
            with open(pkl_path, "rb") as f:
                self._bm25_retriever = pickle.load(f)
        else:
            print("[VectorStoreManager] WARNING: BM25 Index pickle not found locally or on S3. Please run python3 run_ingestion.py first.")
        
        return self._bm25_retriever


    def get_retriever(self, search_type: str = "similarity", k: int = 5):
        """Returns a retriever interface for the vector store."""
        search_kwargs = {"k": k}
        return self.vector_store.as_retriever(search_type=search_type, search_kwargs=search_kwargs)

        
    def similarity_search(self, query: str, k: int = 5, filter: dict = None) -> List[Document]:
        """Performs a raw similarity search - return LangChain Documents"""
        kwargs = {"k": k}
        if filter is not None:
            kwargs["filter"] = filter
        return self.vector_store.similarity_search(query, **kwargs)

    def similarity_search_with_score(self, query: str, k: int = 5) -> List[Document]:
        """Performs a raw similarity search - return LangChain Documents with scores"""
        return self.vector_store.similarity_search_with_relevance_scores(query, k=k)

    def hybrid_search(self, query: str, k: int = 5, filter: dict = None) -> List[Document]:
        """Performs a custom RRF Hybrid Search (Dense + BM25) while respecting metadata filters!"""
        # 1. Get Semantic Docs (Dense Search handles filter natively)
        kwargs = {"k": 20} # Overfetch for math fusion
        if filter is not None:
            kwargs["filter"] = filter
        semantic_docs = self.vector_store.similarity_search(query, **kwargs)
        
        # 2. Get BM25 Docs (Sparse Search ignorers native filters)
        bm25 = self._get_bm25()
        if bm25:
            try:
                bm25_docs = bm25.invoke(query)
            except AttributeError:
                bm25_docs = bm25.get_relevant_documents(query)
        else:
            bm25_docs = []
        
        # 3. Manually filter BM25 Docs
        filtered_bm25 = []
        for doc in bm25_docs[:20]:
            valid = True
            if filter and "lecture_number" in filter and "$lte" in filter["lecture_number"]:
                max_lec = filter["lecture_number"]["$lte"]
                doc_lec = doc.metadata.get("lecture_number", 999)
                if doc_lec > max_lec:
                    valid = False
            if valid:
                filtered_bm25.append(doc)
                
        # 4. RRF (Reciprocal Rank Fusion) Algorithm
        fused_scores = {}
        docs_dict = {}
        
        for rank, doc in enumerate(semantic_docs):
            doc_id = getattr(doc, "id", None) or doc.metadata.get("id") or doc.page_content[:300]
            # Semantic Weight: 0.9
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (0.9 / (rank + 60))
            docs_dict[doc_id] = doc
            
        for rank, doc in enumerate(filtered_bm25):
            doc_id = getattr(doc, "id", None) or doc.metadata.get("id") or doc.page_content[:300]
            # BM25 Weight: 0.1
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (0.1 / (rank + 60))
            docs_dict[doc_id] = doc
            
        # 5. Sort and return top K
        reranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        return [docs_dict[doc_id] for doc_id, score in reranked[:k]]

    def fetch_by_id(self, chunk_id: str) -> Document | None:
        """Fetches a single document by its chunk_id directly from Pinecone."""
        try:
            fetch_res = self.vector_store.index.fetch(ids=[chunk_id])
            vectors = fetch_res.get("vectors", {})
            if chunk_id in vectors:
                vec = vectors[chunk_id]
                metadata = vec.get("metadata", {})
                text = metadata.pop("text", "")
                return Document(page_content=text, metadata=metadata, id=chunk_id)
        except Exception as e:
            print(f"[VectorStoreManager] Error fetching chunk {chunk_id}: {e}")
        return None

    def fetch_lecture_for_summary(self, lecture_number: int) -> List[Document]:
        """Fetches all chunks matching the lecture number using metadata filter."""
        return self.similarity_search(
            query="",
            k=10000,
            filter={"lecture_number": lecture_number}
        )

    def fetch_lecture_range_for_summary(self, start_lecture: int, end_lecture: int) -> List[Document]:
        """Fetches all chunks matching the lecture range [start_lecture, end_lecture]."""
        filter_query = {
            "lecture_number": {
                "$gte": start_lecture,
                "$lte": end_lecture
            }
        }
        return self.similarity_search(
            query="",
            k=10000,
            filter=filter_query
        )