import os
import boto3
from typing import Optional
from dotenv import load_dotenv

from domain.chat_session import ChatSession
from domain.chat_message import ChatMessage

# Load env variables for AWS credentials
load_dotenv()

class ChatHistoryStore:
    """
    Manages ChatSession objects using AWS DynamoDB for a stateless architecture.
    Sessions are persisted to the cloud rather than local disk.
    """

    def __init__(self, table_name: str = "courselens-sessions"):
        self.table_name = table_name
        # boto3.resource allows us to interact with DynamoDB using native Python dictionaries
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(self.table_name)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_session(self, mode: str = "general") -> ChatSession:
        """Creates a new session, persists it to DynamoDB, and returns it."""
        session = ChatSession(mode=mode)
        self.save_session(session)
        return session

    def load_session(self, session_id: str) -> Optional[ChatSession]:
        """Loads a session from DynamoDB by its ID. Returns None if not found."""
        try:
            response = self.table.get_item(Key={'session_id': session_id})
            if 'Item' not in response:
                return None
            data = response['Item']
            return ChatSession.model_validate(data)
        except Exception as e:
            print(f"Error loading session {session_id} from DynamoDB: {e}")
            return None

    def save_session(self, session: ChatSession) -> None:
        """Persists a session to DynamoDB."""
        try:
            # We use model_dump() to get a native Python dictionary instead of a JSON string
            data = session.model_dump()
            self.table.put_item(Item=data)
        except Exception as e:
            print(f"Error saving session {session.session_id} to DynamoDB: {e}")

    def append_message(self, session_id: str, role: str, content: str) -> Optional[ChatMessage]:
        """
        Loads the session, appends a message, saves, and returns the new message.
        """
        session = self.load_session(session_id)
        if session is None:
            return None
        msg = session.add_message(role=role, content=content)
        self.save_session(session)
        return msg

    def list_sessions(self) -> list[str]:
        """Returns a list of all known session IDs from DynamoDB."""
        try:
            # In a massive production app, we would use a Global Secondary Index here.
            # For this scale, a simple Scan projecting just the session_id is perfect.
            response = self.table.scan(ProjectionExpression="session_id")
            ids = [item['session_id'] for item in response.get('Items', [])]
            return sorted(ids)
        except Exception as e:
            print(f"Error listing sessions from DynamoDB: {e}")
            return []
