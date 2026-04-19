from services.rag.chroma_retriever import VectorStoreManager
from services.rag.bm25_retriever import BM25Manager
from langchain_huggingface import HuggingFaceEmbeddings

def main():
    emb = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
    vsm = VectorStoreManager(embeddings_model=emb)
    bm25 = BM25Manager()
    
    docs = vsm.similarity_search("reverse_iterator", k=1)
    print("VectorStore docs:")
    for d in docs:
        print(d.metadata, getattr(d, 'id', None))
        
    docs2 = bm25.search("reverse_iterator", k=1)
    print("BM25 docs:")
    for d in docs2:
        print(d.metadata, getattr(d, 'id', None))

if __name__ == "__main__":
    main()
