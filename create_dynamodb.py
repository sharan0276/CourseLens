import os
import boto3
from dotenv import load_dotenv

def create_table():
    load_dotenv()
    
    # Boto3 automatically reads the AWS keys from the environment variables we added to .env
    dynamodb = boto3.client('dynamodb')
    
    table_name = 'courselens-sessions'
    
    print(f"Attempting to create DynamoDB table: {table_name}...")
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    'AttributeName': 'session_id',
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'session_id',
                    'AttributeType': 'S'
                }
            ],
            BillingMode='PAY_PER_REQUEST' # Free tier compatible
        )
        print(f"Table '{table_name}' creation initiated. Status: {response['TableDescription']['TableStatus']}")
    except dynamodb.exceptions.ResourceInUseException:
        print(f"Success! Table '{table_name}' already exists.")
    except Exception as e:
        print(f"Error creating table: {str(e)}")

if __name__ == "__main__":
    create_table()
