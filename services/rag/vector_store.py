import os
from typing import List
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

class VectorStoreManager:
    """Manages the Chroma vector database for storing and retrieving documents."""

    def __init__(self, embeddings_model: Embeddings, persist_directory: str = "CourseLens_data/chroma_db"):
        self.embeddings = embeddings_model
        self.persist_directory = persist_directory
        
        # Initialize chroma db
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory
        )

    def add_documents(self, documents: List[Document]) -> None:
        """Adds standard Langchain Documents to the vector store."""
        if not documents:
            return
        self.vector_store.add_documents(documents)

    def get_retriever(self, search_type: str = "similarity", k: int = 4, **kwargs):
        """Returns a retriever interface for the vector store."""
        search_kwargs = {"k": k, **kwargs}
        return self.vector_store.as_retriever(search_type=search_type, search_kwargs=search_kwargs)
        
    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """Performs a raw similarity search."""
        return self.vector_store.similarity_search(query, k=k)
