from typing import List
from langchain_core.embeddings import Embeddings
from services.embedding.embedder import Embedder

class CourseLensEmbeddings(Embeddings):
    """
    Adapter class that implements the LangChain Embeddings interface
    using the existing CourseLens Embedder service.
    """
    def __init__(self, embedder: Embedder):
        self.embedder = embedder

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed search docs."""
        # Wrap texts in dicts as expected by embed_chunks
        chunks = [{"text": text} for text in texts]
        embedded_chunks = self.embedder.embed_chunks(chunks)
        return [chunk["embedding"] for chunk in embedded_chunks]

    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""
        # Wrap single text in dict
        chunks = [{"text": text}]
        embedded_chunks = self.embedder.embed_chunks(chunks)
        return embedded_chunks[0]["embedding"]
