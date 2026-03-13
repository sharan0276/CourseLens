import json
import uuid
import os
from typing import List, Dict, Optional, Any


class SessionStore:
    """
    File-backed JSON store for chat sessions.

    Schema:
    {
        "<session_id>": {
            "pipeline_type": "general" | "coding",
            "history": [
                {"role": "human" | "assistant", "content": "..."},
                ...
            ]
        }
    }
    """

    def __init__(self, store_path: str = "CourseLens_data/chat_sessions.json"):
        self.store_path = store_path
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        if not os.path.exists(store_path):
            self._write({})

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _read(self) -> Dict[str, Any]:
        with open(self.store_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── Public API ───────────────────────────────────────────────────────────

    def create_session(self, pipeline_type: str = "general") -> str:
        """Creates a new session and returns its ID."""
        session_id = str(uuid.uuid4())
        data = self._read()
        data[session_id] = {"pipeline_type": pipeline_type, "history": []}
        self._write(data)
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Returns the session dict or None if it does not exist."""
        return self._read().get(session_id)

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Returns the list of history messages for a session."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")
        return session["history"]

    def append_message(self, session_id: str, role: str, content: str) -> None:
        """Appends a single message (role: 'human' or 'assistant') to a session."""
        data = self._read()
        if session_id not in data:
            raise ValueError(f"Session '{session_id}' not found.")
        data[session_id]["history"].append({"role": role, "content": content})
        self._write(data)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Returns a summary list of all sessions."""
        data = self._read()
        return [
            {
                "session_id": sid,
                "pipeline_type": info.get("pipeline_type", "general"),
                "turns": len(info.get("history", [])) // 2,
            }
            for sid, info in data.items()
        ]

    def delete_session(self, session_id: str) -> bool:
        """Deletes a session. Returns True if removed, False if not found."""
        data = self._read()
        if session_id not in data:
            return False
        del data[session_id]
        self._write(data)
        return True
