import os
from typing import List
from langchain_core.documents import Document
from services.chunking.chunk_builder import ChunkBuilder


class JSONSlideLoader:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.chunk_builder = ChunkBuilder()

    def load(self) -> List[Document]:
        documents = []
        if not os.path.exists(self.data_dir):
            print(f"Warning: Directory {self.data_dir} does not exist.")
            return documents

        for filename in os.listdir(self.data_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(self.data_dir, filename)
                try:
                    # Leverage the existing ChunkBuilder
                    parent_chunks, child_chunks = self.chunk_builder.build_from_json(file_path)
                    
                    # Store parent chunks in our vector DB to supply context
                    for chunk in parent_chunks:
                        metadata = chunk.get("metadata", {})
                        
                        # Langchain expects metadata values to be str, int, float, or bool
                        # We must sanitize the metadata dict just in case
                        safe_metadata = {
                            k: v for k, v in metadata.items() 
                            if isinstance(v, (str, int, float, bool))
                        }
                        
                        doc = Document(
                            page_content=chunk.get("text", ""), 
                            metadata=safe_metadata
                        )
                        documents.append(doc)
                        
                    # Also store child chunks
                    for chunk in child_chunks:
                        metadata = chunk.get("metadata", {})
                        
                        safe_metadata = {
                            k: v for k, v in metadata.items() 
                            if isinstance(v, (str, int, float, bool))
                        }
                        
                        doc = Document(
                            page_content=chunk.get("text", ""), 
                            metadata=safe_metadata
                        )
                        documents.append(doc)

                except Exception as e:
                    print(f"Error loading {file_path}: {e}")

        return documents
