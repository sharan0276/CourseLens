import uuid
from datetime import datetime
from typing import List
from pydantic import BaseModel, Field

from domain.chat_message import ChatMessage


class ChatSession(BaseModel):
    """
    Represents a full conversation session between the user and the assistant.
    """
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the session."
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the session was created."
    )
    mode: str = Field(
        default="general",
        description="Pipeline mode: 'general' for Q&A, 'coding' for Socratic tutor."
    )
    messages: List[ChatMessage] = Field(
        default_factory=list,
        description="Ordered list of all messages in this session."
    )

    def add_message(self, role: str, content: str) -> ChatMessage:
        """Appends a new message to the session and returns it."""
        msg = ChatMessage(role=role, content=content)
        self.messages.append(msg)
        return msg
