import chromadb

class VectorStore:
    """
    Responsible for managing ChrtomeDB connection and storing chunks.
    Handles all database operations- setup, storage and retrieval.
    """
    def __init__(self, db_path: str = "./courselens_db"):
        print(f"Connecting to ChromaDB at {db_path}")
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name="course_lens",
            metadata={"hnsw:space": "cosine"}
        )
        print("Connected to ChromaDB")

    
    def store(self, chunks: list):
        """
        Stores embedded chunks into ChromaDB.
        """
        if not chunks:
            print("No chunks to store")
            return
        
        ids = [chunk["id"] for chunk in chunks]
        embeddings = [chunk["embedding"] for chunk in chunks]
        metadatas = [self._sanitize_metadata(chunk["metadata"]) for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]

        print(f"Storing {len(chunks)} chunks in ChromaDB...")
        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )
        print("Chunks stored successfully")

    def reset_collection(self):
        """Deletes and recreates collection — use when re-ingesting from scratch."""
        self.client.delete_collection("course_lens")
        self.collection = self.client.get_or_create_collection(
            name="course_lens",
            metadata={"hnsw:space": "cosine"}
        )
        print("Collection reset successfully")



    def _sanitize_metadata(self, metadata : dict) -> dict:
        """
        ChromaDB supports str, int, float, bool in metadata.
        Convert the rest to empty string.
        """
        sanitized = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                sanitized[k] = v
            else:
                sanitized[k] = ""
        return sanitized