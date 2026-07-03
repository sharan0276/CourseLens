import os
import boto3
from botocore.exceptions import ClientError
from typing import List

class S3Service:
    def __init__(self, bucket_name: str, region: str = "us-east-1"):
        self.s3 = boto3.client('s3', region_name=region)
        self.bucket_name = bucket_name

    def download_folder(self, prefix: str, local_dir: str, extensions: List[str] = None):
        """
        Downloads all files from S3 with a specific prefix to a local directory.
        Optionally filter by extensions (e.g., ['.pptx', '.pdf']).
        """
        os.makedirs(local_dir, exist_ok=True)
        try:
            paginator = self.s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    key = obj['Key']
                    if key.endswith('/'): # Skip directory objects
                        continue
                        
                    if extensions and not any(key.endswith(ext) for ext in extensions):
                        continue
                        
                    # Calculate local path
                    relative_path = os.path.relpath(key, prefix)
                    local_file_path = os.path.join(local_dir, relative_path)
                    
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    print(f"Downloading {key} to {local_file_path}...")
                    self.s3.download_file(self.bucket_name, key, local_file_path)
                    
        except ClientError as e:
            print(f"Error downloading from S3: {e}")
            raise e

    def download_file(self, s3_key: str, local_file_path: str):
        """
        Downloads a single file from S3.
        """
        try:
            print(f"Downloading s3://{self.bucket_name}/{s3_key} to {local_file_path}...")
            self.s3.download_file(self.bucket_name, s3_key, local_file_path)
        except ClientError as e:
            print(f"Error downloading from S3: {e}")
            raise e

    def upload_file(self, local_file_path: str, s3_key: str):
        """
        Uploads a single file to S3.
        """
        try:
            print(f"Uploading {local_file_path} to s3://{self.bucket_name}/{s3_key}...")
            self.s3.upload_file(local_file_path, self.bucket_name, s3_key)
        except ClientError as e:
            print(f"Error uploading to S3: {e}")
            raise e

    def upload_folder(self, local_dir: str, prefix: str):
        """
        Uploads all files in a local directory to S3 under the given prefix.
        """
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                if file.startswith('.'):
                    continue
                
                local_path = os.path.join(root, file)
                # Ensure the S3 key structure matches the desired prefix
                relative_path = os.path.relpath(local_path, local_dir)
                s3_key = os.path.join(prefix, relative_path).replace("\\", "/")
                
                self.upload_file(local_path, s3_key)

    def generate_presigned_url(self, object_name: str, expiration=3600):
        """
        Generates a presigned URL for an S3 object.
        """
        try:
            response = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
                ExpiresIn=expiration
            )
        except ClientError as e:
            print(f"Error generating presigned URL: {e}")
            return None
        return response
