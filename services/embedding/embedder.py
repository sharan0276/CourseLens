from sentence_transformers import SentenceTransformer
import torch

class Embedder:
    """
    Responsible for converting chunk text into vectors.
    Using bge-m3 model - Supports higher token limit and handles larger parent chunks easily.
    """
    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 32,
        show_progress_bar: bool = True,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self.show_progress_bar = show_progress_bar
        self.device = device

        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name, device=device)
        print(f"Model loaded successfully")

    def embed_chunks(self, chunks: list) -> list:
        """
        Embeds chunks into vectors.
        """
        if not chunks: 
            return chunks
        
        texts = [chunk["text"] for chunk in chunks]
        print(f"Embedding {len(texts)} chunks...")
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=self.show_progress_bar,
            convert_to_numpy=True,
            normalize_embeddings=True
        ).tolist()

        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
        
        return chunks