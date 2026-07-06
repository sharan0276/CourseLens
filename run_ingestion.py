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
    import argparse
    parser = argparse.ArgumentParser(description="Run CourseLens Ingestion Pipeline.")
    parser.add_argument("--file", type=str, help="Path to a single PPTX or PDF file to ingest.")
    args = parser.parse_args()

    load_dotenv()
    # Ensure this matches your S3 bucket name
    s3_bucket = os.getenv("S3_BUCKET_NAME", "courselens-data-bucket-test-01")
    s3_service = S3Service(bucket_name=s3_bucket)
    
    # Define local folders
    tmp_raw_folder = "CourseLens_data/tmp_raw/"
    json_folder = "CourseLens_data/processed_data/"
    images_folder = "CourseLens_data/images/"
    
    llm = get_vertex_llm(temperature=0.0)
    service = IngestionService(llm=llm)
    
    try:
        if args.file:
            local_path = args.file
            was_downloaded = False
            
            # If the file doesn't exist locally, try downloading it from S3
            if not os.path.exists(local_path):
                print(f"File {local_path} not found locally. Attempting to download from S3...")
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                s3_service.download_file(local_path, local_path)
                was_downloaded = True

            print(f"Starting single-file ingestion for: {local_path}")
            result = service.ingest_file(local_path)
            print("Single-file ingestion completed successfully!")
            print(f"Result: {result}")

            # Upload the single processed JSON file back to S3
            filename = os.path.basename(local_path)
            ext = os.path.splitext(filename)[1].lower()
            json_name = filename.replace(ext, ".json")
            local_json = os.path.join(json_folder, json_name)
            
            if os.path.exists(local_json):
                print(f"Uploading processed JSON back to S3: {local_json}")
                s3_service.upload_file(local_json, f"CourseLens_data/processed_data/{json_name}")
                
            print("Uploading updated BM25 index back to S3...")
            s3_service.upload_file("CourseLens_data/bm25_retriever.pkl", "CourseLens_data/bm25_retriever.pkl")

            # Upload syllabus_topics.json if running locally
            if not os.getenv("S3_BUCKET_NAME"):
                print("Uploading local syllabus_topics.json back to S3...")
                s3_service.upload_file("config/syllabus_topics.json", "config/syllabus_topics.json")
                
            print("\nUploading extracted images back to S3...")
            s3_service.upload_folder(images_folder, "CourseLens_data/images")

            # Clean up the temporary raw file if it was downloaded from S3
            if was_downloaded and os.path.exists(local_path):
                print(f"Cleaning up temporary downloaded file: {local_path}")
                try:
                    os.remove(local_path)
                except Exception as e:
                    print(f"Failed to delete temporary file {local_path}: {e}")
            
        else:
            print(f"Downloading raw presentations from S3 bucket '{s3_bucket}' to '{tmp_raw_folder}'...")
            # S3 path prefix is "CourseLens_data/" based on our upload script
            s3_service.download_folder("CourseLens_data/", tmp_raw_folder, extensions=['.pptx', '.pdf'])
            
            print(f"Starting ingestion for folder: {tmp_raw_folder}")
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
            
            if not os.getenv("S3_BUCKET_NAME"):
                print("Uploading local syllabus_topics.json back to S3...")
                s3_service.upload_file("config/syllabus_topics.json", "config/syllabus_topics.json")
                
            print("\nCleaning up temporary raw files...")
            if os.path.exists(tmp_raw_folder):
                shutil.rmtree(tmp_raw_folder)
                
            print("S3 Ingestion Pipeline complete!")
    
    except Exception as e:
        print(f"Ingestion failed with error: {e}")

if __name__ == "__main__":
    main()
