import os
import json
from typing import Optional

from domain.chat_session import ChatSession
from domain.chat_message import ChatMessage


class ChatHistoryStore:
    """
    Manages ChatSession objects: creates, loads, saves, and lists them.
    Sessions are persisted as individual JSON files on disk so they can be resumed.
    """

    def __init__(self, storage_dir: str = "CourseLens_data/chat_sessions"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.storage_dir, f"{session_id}.json")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_session(self, mode: str = "general") -> ChatSession:
        """Creates a new session, persists it, and returns it."""
        session = ChatSession(mode=mode)
        self.save_session(session)
        return session

    def load_session(self, session_id: str) -> Optional[ChatSession]:
        """Loads a session from disk by its ID. Returns None if not found."""
        path = self._session_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ChatSession.model_validate(data)

    def save_session(self, session: ChatSession) -> None:
        """Persists a session to disk as JSON."""
        path = self._session_path(session.session_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(session.model_dump_json(indent=2))

    def append_message(self, session_id: str, role: str, content: str) -> Optional[ChatMessage]:
        """
        Loads the session, appends a message, saves, and returns the new message.
        Returns None if session not found.
        """
        session = self.load_session(session_id)
        if session is None:
            return None
        msg = session.add_message(role=role, content=content)
        self.save_session(session)
        return msg

    def list_sessions(self) -> list[str]:
        """Returns a sorted list of all known session IDs."""
        ids = []
        for fname in os.listdir(self.storage_dir):
            if fname.endswith(".json"):
                ids.append(fname.replace(".json", ""))
        return sorted(ids)
