from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """
    Represents a single message in a chat session.
    """
    role: Literal["user", "assistant"] = Field(
        ...,
        description="Who sent the message: 'user' or 'assistant'."
    )
    content: str = Field(
        ...,
        description="The text content of the message."
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the message was created."
    )
