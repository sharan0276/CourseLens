import os
import sys

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.llm_factory import get_vertex_llm
from services.ingestion.ingestion_service import IngestionService

def main():
    # Define the input folder (current directory for test)
    input_folder = "CourseLens_data/ppts/"
    json_folder = "CourseLens_data/processed_data/"
    
    print(f"Starting ingestion for folder: {input_folder}")
    
    llm = get_vertex_llm(temperature=0.0)
    
    try:
        service = IngestionService(llm=llm)
        result = service.ingest_folder(input_folder)
        print("Ingestion completed successfully!")
        print(f"Result: {result}")

        service.create_embeddings_for_folder(json_folder)
        print("Embeddings created successfully!")
    
    except Exception as e:
        print(f"Ingestion failed with error: {e}")

if __name__ == "__main__":
    main()
