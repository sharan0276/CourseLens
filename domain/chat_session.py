import uuid
from datetime import datetime
from typing import List, Optional
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
    title: Optional[str] = Field(
        default=None,
        description="Optional human-readable title for the session."
    )
    mode: str = Field(
        default="general",
        description="Pipeline mode: 'general' for direct Q&A, 'coding' for code debugging, 'socratic' for concept understanding."
    )
    messages: List[ChatMessage] = Field(
        default_factory=list,
        description="Ordered list of all messages in this session."
    )
    history_summary: Optional[str] = Field(
        default=None,
        description="A running summary of older messages."
    )
    summary_index: int = Field(
        default=0,
        description="The index in 'messages' up to which the history_summary covers."
    )

    # Socratic state — all optional so existing sessions load without errors
    active_problem_query: Optional[str] = Field(
        default=None,
        description="Original student query that started the current Socratic loop."
    )
    ta_stage: int = Field(
        default=0,
        description="Current Socratic stage. 0 = not in a loop, 1-3 = active stages, 4 = overflow direct answer."
    )
    anchored_chunk_ids: List[str] = Field(
        default_factory=list,
        description="Chunk IDs fetched at stage 1 and reused for all stages in this loop."
    )
    selected_topics: List[str] = Field(
        default_factory=list,
        description="Topics selected by Flash for the current Socratic loop."
    )

    def add_message(self, role: str, content: str) -> ChatMessage:
        """Appends a new message to the session and returns it."""
        msg = ChatMessage(role=role, content=content)
        self.messages.append(msg)
        return msg
   
    def start_socratic_loop(self, query: str, chunk_ids: List[str], topics: List[str]) -> None:
        """Sets up state for a new Socratic loop."""
        self.active_problem_query = query
        self.ta_stage = 1
        self.anchored_chunk_ids = chunk_ids
        self.selected_topics = topics

    def advance_stage(self) -> None:
        """Moves to the next stage."""
        self.ta_stage += 1

    def reset_socratic_state(self) -> None:
        """Clears all Socratic loop state after completion."""
        self.active_problem_query = None
        self.ta_stage = 0
        self.anchored_chunk_ids = []
        self.selected_topics = []

    def in_socratic_loop(self) -> bool:
        """Returns True if a Socratic loop is currently active."""
        return self.ta_stage > 0