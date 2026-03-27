import os
import pickle
from typing import List
from langchain_core.documents import Document

class BM25Manager:
    """Read-only interface to the global BM25 sparse keyword index."""
    def __init__(self, pkl_path: str = "CourseLens_data/bm25_retriever.pkl"):
        self.pkl_path = pkl_path
        self._bm25_retriever = None

    def _get_bm25(self):
        """Self-healing BM25 loader from disk -> memory"""
        if self._bm25_retriever is not None:
            return self._bm25_retriever
            
        if os.path.exists(self.pkl_path):
            with open(self.pkl_path, "rb") as f:
                self._bm25_retriever = pickle.load(f)
        else:
            print("[BM25Manager] BM25 Index not found on disk. Auto-healing from ChromaDB...")
            from langchain_community.retrievers import BM25Retriever
            import chromadb
            
            # Extract raw corpus to self-heal
            client = chromadb.PersistentClient(path="CourseLens_data/chroma_db")
            collection = client.get_collection("course_lens")
            all_data = collection.get(include=["documents", "metadatas"])
            
            docs = []
            for t, m, i in zip(all_data['documents'], all_data['metadatas'], all_data['ids']):
                docs.append(Document(page_content=t, metadata=m, id=i))
            
            if docs:
                self._bm25_retriever = BM25Retriever.from_documents(docs)
                with open(self.pkl_path, "wb") as f:
                    pickle.dump(self._bm25_retriever, f)
                    
        return self._bm25_retriever

    def search(self, query: str, k: int = 20, filter: dict = None) -> List[Document]:
        """Sparse keyword search with manual metadata lecture filtering"""
        bm25 = self._get_bm25()
        if not bm25:
            return []
            
        # BM25 ignores Langchain's native metadata filters natively, so we post-filter
        try:
            bm25_docs = bm25.invoke(query)
        except AttributeError:
            bm25_docs = bm25.get_relevant_documents(query)
        
        filtered_docs = []
        for doc in bm25_docs:
            valid = True
            if filter and "lecture_number" in filter and "$lte" in filter["lecture_number"]:
                max_lec = filter["lecture_number"]["$lte"]
                doc_lec = doc.metadata.get("lecture_number", 999)
                if doc_lec > max_lec:
                    valid = False
            
            if valid:
                filtered_docs.append(doc)
                
            if len(filtered_docs) == k:
                break
                
        return filtered_docs
