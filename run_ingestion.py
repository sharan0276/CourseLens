import os
import sys

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import shutil
from services.llm_factory import get_vertex_llm
from services.ingestion.ingestion_service import IngestionService
from services.s3_service import S3Service
from dotenv import load_dotenv

def main():
    load_dotenv()
    # Ensure this matches your S3 bucket name
    s3_bucket = os.getenv("S3_BUCKET_NAME", "courselens-data-bucket-test-01")
    s3_service = S3Service(bucket_name=s3_bucket)
    
    # Define local folders
    tmp_raw_folder = "CourseLens_data/tmp_raw/"
    json_folder = "CourseLens_data/processed_data/"
    images_folder = "CourseLens_data/images/"
    
    print(f"Downloading raw presentations from S3 bucket '{s3_bucket}' to '{tmp_raw_folder}'...")
    # S3 path prefix is "CourseLens_data/" based on our upload script
    s3_service.download_folder("CourseLens_data/", tmp_raw_folder, extensions=['.pptx', '.pdf'])
    
    print(f"Starting ingestion for folder: {tmp_raw_folder}")
    
    llm = get_vertex_llm(temperature=0.0)
    
    try:
        service = IngestionService(llm=llm)
        result = service.ingest_folder(tmp_raw_folder)
        print("Ingestion completed successfully!")
        print(f"Result: {result}")

        service.create_embeddings_for_folder(json_folder)
        print("Embeddings created successfully!")
        
        print("\nUploading extracted images back to S3...")
        s3_service.upload_folder(images_folder, "CourseLens_data/images")
        
        print("Uploading processed JSON data back to S3...")
        s3_service.upload_folder(json_folder, "CourseLens_data/processed_data")
        
        print("Uploading compiled BM25 index back to S3...")
        s3_service.upload_file("CourseLens_data/bm25_retriever.pkl", "CourseLens_data/bm25_retriever.pkl")
        
        print("\nCleaning up temporary raw files...")
        if os.path.exists(tmp_raw_folder):
            shutil.rmtree(tmp_raw_folder)
            
        print("S3 Ingestion Pipeline complete!")
    
    except Exception as e:
        print(f"Ingestion failed with error: {e}")

if __name__ == "__main__":
    main()
