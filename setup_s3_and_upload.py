import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

def create_and_populate_s3(bucket_name, region="us-east-1"):
    load_dotenv()
    
    # Initialize S3 client
    s3_client = boto3.client('s3', region_name=region)
    
    # 1. Create the bucket
    print(f"Attempting to create S3 bucket: {bucket_name}...")
    try:
        if region == "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print(f"Success! Bucket '{bucket_name}' created.")
    except ClientError as e:
        if e.response['Error']['Code'] in ['BucketAlreadyExists', 'BucketAlreadyOwnedByYou']:
            print(f"Bucket '{bucket_name}' already exists. Proceeding to upload...")
        else:
            print(f"Error creating bucket: {e}")
            return

    # 2. Upload the local files
    source_dir = "CourseLens_data"
    if not os.path.exists(source_dir):
        print(f"Error: Directory '{source_dir}' not found locally.")
        return

    print(f"\nUploading files from '{source_dir}' to S3 bucket '{bucket_name}'...")
    
    upload_count = 0
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            # Strictly upload only raw presentation files
            if not (file.endswith('.pptx') or file.endswith('.pdf')):
                continue
                
            local_path = os.path.join(root, file)
            # The S3 object key should be relative to the CourseLens_data folder
            s3_key = local_path 
            
            try:
                s3_client.upload_file(local_path, bucket_name, s3_key)
                print(f"  Uploaded: {s3_key}")
                upload_count += 1
            except Exception as e:
                print(f"  Failed to upload {local_path}: {e}")
                
    print(f"\nFinished uploading {upload_count} raw presentation files to S3 bucket '{bucket_name}'.")

if __name__ == "__main__":
    # S3 bucket names MUST be globally unique across all of AWS!
    # Change this to something unique to you (e.g., courselens-sharan-12345)
    MY_BUCKET_NAME = "courselens-data-bucket-test-01" 
    create_and_populate_s3(MY_BUCKET_NAME)
