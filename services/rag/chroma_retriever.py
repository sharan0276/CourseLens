from typing import List
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from langchain_chroma import Chroma


class VectorStoreManager:
    """ Read-only interface to ChromaDB for LangChain RAG pipeline.
    Connects to existing collection built by run_ingestion.py"""

    def __init__(self, embeddings_model: Embeddings, persist_directory: str = "CourseLens_data/chroma_db", collection_name: str = "course_lens"):
        self.embeddings = embeddings_model
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        
        # Initialize chroma db
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
            collection_name=self.collection_name
        )
        self._bm25_retriever = None
        print(f"Connected to ChromaDB collection: {self.collection_name} at {self.persist_directory}")

    def _get_bm25(self):
        """Self-healing BM25 Loader"""
        if self._bm25_retriever is not None:
            return self._bm25_retriever
            
        import os, pickle
        pkl_path = "CourseLens_data/bm25_retriever.pkl"
        if os.path.exists(pkl_path):
            with open(pkl_path, "rb") as f:
                self._bm25_retriever = pickle.load(f)
        else:
            print("[VectorStoreManager] BM25 Index not found. Auto-healing from ChromaDB...")
            from langchain_community.retrievers import BM25Retriever
            from langchain_core.documents import Document
            
            all_data = self.vector_store.get(include=["documents", "metadatas"])
            docs = []
            for t, m, i in zip(all_data['documents'], all_data['metadatas'], all_data['ids']):
                docs.append(Document(page_content=t, metadata=m, id=i))
            
            if docs:
                self._bm25_retriever = BM25Retriever.from_documents(docs)
                with open(pkl_path, "wb") as f:
                    pickle.dump(self._bm25_retriever, f)
        
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