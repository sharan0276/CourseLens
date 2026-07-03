import os
from pinecone import Pinecone

class VectorStore:
    """
    Responsible for managing Pinecone connection and storing chunks.
    Handles cloud-level setup, storage and resets.
    """
    def __init__(self, db_path: str = None):
        # db_path parameter is maintained for interface compatibility but ignored
        api_key = os.getenv("PINECONE_API_KEY")
        host = os.getenv("PINECONE_INDEX_HOST")
        if not api_key or not host:
            raise ValueError("PINECONE_API_KEY and PINECONE_INDEX_HOST must be set in environmental variables")
            
        print("Connecting to Pinecone Cloud Index...")
        self.pc = Pinecone(api_key=api_key)
        self.index = self.pc.Index(host=host)
        print("Connected to Pinecone successfully")

    def store(self, chunks: list):
        """
        Stores embedded chunks into Pinecone.
        """
        if not chunks:
            print("No chunks to store")
            return
        
        vectors_to_upsert = []
        for chunk in chunks:
            sanitized_meta = self._sanitize_metadata(chunk["metadata"])
            # Pinecone requires raw text to be stored in metadata under a key
            sanitized_meta["text"] = chunk["text"]
            
            vectors_to_upsert.append({
                "id": chunk["id"],
                "values": chunk["embedding"],
                "metadata": sanitized_meta
            })

        print(f"Storing {len(chunks)} chunks in Pinecone...")
        
        # Batch upsert in groups of 100 to stay safely under Pinecone payload size limit (2MB)
        batch_size = 100
        for i in range(0, len(vectors_to_upsert), batch_size):
            batch = vectors_to_upsert[i:i + batch_size]
            self.index.upsert(vectors=batch)
            
        print("Chunks stored successfully in Pinecone")

    def reset_collection(self):
        """Deletes all vectors from the Pinecone index — use when re-ingesting from scratch."""
        print("Resetting Pinecone index (deleting all vectors)...")
        try:
            self.index.delete(delete_all=True)
            print("Pinecone index reset successfully")
        except Exception as e:
            print(f"Error resetting Pinecone index: {e}")

    def _sanitize_metadata(self, metadata : dict) -> dict:
        """
        Pinecone metadata supports: String, Number (Integer or Float), Boolean, or List of Strings.
        Convert other types to string.
        """
        sanitized = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                sanitized[k] = v
            elif isinstance(v, list):
                # Ensure it's a list of strings
                sanitized[k] = [str(x) for x in v]
            else:
                sanitized[k] = str(v) if v is not None else ""
        return sanitized