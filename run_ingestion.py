import os
import sys

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langchain_google_genai import ChatGoogleGenerativeAI
from services.ingestion.ingestion_service import IngestionService

def main():
    # Define the input folder (current directory for test)
    input_folder = "CourseLens_data/ppts/"
    json_folder = "CourseLens_data/processed_data/"
    
    print(f"Starting ingestion for folder: {input_folder}")
    
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Warning: GEMINI_API_KEY not found. Chunk summarization will be skipped or may fail.")
        llm = None
    else:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
        )
    
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
