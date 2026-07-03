import chromadb
from services.embedding.embedder import Embedder
from services.rag.retrieval_service import RetrievalService
from services.rag.pinecone_retriever import VectorStoreManager
from services.rag.bm25_retriever import BM25Manager

def main():
    print("\n── Connecting to Production Retrieval Stack ──")
    embedder = Embedder()
    vsm = VectorStoreManager(embeddings_model=embedder)
    bm25 = BM25Manager()
    retriever = RetrievalService(vector_store_manager=vsm, bm25_manager=bm25)

    q = "what are goals of software engineering?"
    print(f"\nQuery: {q}")
    docs = retriever.retrieve(q, k=5, disable_swapping=True)
    print("\nFinal Top 5:")
    for i, d in enumerate(docs):
        print(f"[{i+1}] {d.metadata.get('title')} (Lecture {d.metadata.get('lecture_number')}, Slide {d.metadata.get('slide_number')})")
        print(f"Content preview: {d.page_content[:150]}...\n")

if __name__ == "__main__":
    main()
