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
        print(f"Connected to ChromaDB collection: {self.collection_name} at {self.persist_directory}")


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