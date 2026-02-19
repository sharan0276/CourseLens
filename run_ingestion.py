import os
import sys

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.ingestion.ingestion_service import IngestionService

def main():
    # Define the input folder (current directory for test)
    input_folder = "CourseLens_data/ppts/"
    input_folder2 = "CourseLens_data/pdfs/"
    
    print(f"Starting ingestion for folder: {input_folder}")
    
    try:
        service = IngestionService()
        result = service.ingest_folder(input_folder)
        print("Ingestion completed successfully!")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Ingestion failed with error: {e}")
        
    print(f"Starting ingestion for folder: {input_folder2}")
    
    try:
        service = IngestionService()
        result = service.ingest_folder(input_folder2)
        print("Ingestion completed successfully!")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Ingestion failed with error: {e}")

if __name__ == "__main__":
    main()
