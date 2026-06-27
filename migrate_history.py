import os
import json
import boto3
from dotenv import load_dotenv

def migrate_history():
    load_dotenv()
    
    # We use 'resource' instead of 'client' because it automatically converts Python dictionaries into DynamoDB format!
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('courselens-sessions')
    
    history_dir = "CourseLens_data/chat_sessions"
    
    if not os.path.exists(history_dir):
        print(f"Directory {history_dir} not found. Nothing to migrate.")
        return

    files = [f for f in os.listdir(history_dir) if f.endswith('.json')]
    print(f"Found {len(files)} chat sessions to migrate...")

    for fname in files:
        file_path = os.path.join(history_dir, fname)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        try:
            # Insert the entire JSON document into DynamoDB in one line!
            table.put_item(Item=data)
            print(f"Migrated: {fname}")
        except Exception as e:
            print(f"Failed to migrate {fname}. Error: {e}")
            
    print("Migration complete!")

if __name__ == "__main__":
    migrate_history()
