from typing import Optional
from services.session.session_store import SessionStore


class ChatSession:
    """
    Orchestrates a multi-turn conversation by tying a SessionStore to a RAG pipeline.

    Usage:
        store = SessionStore()
        session = ChatSession(pipeline=rag_pipeline, session_store=store)
        reply = session.send_message(session_id, "What is a pointer?")
    """

    def __init__(self, pipeline, session_store: Optional[SessionStore] = None):
        """
        Args:
            pipeline: An instance of RAGPipeline or RAGPipelineCoding.
            session_store: Shared SessionStore instance (creates a default one if omitted).
        """
        self.pipeline = pipeline
        self.store = session_store or SessionStore()

    def send_message(self, session_id: str, user_message: str) -> str:
        """
        Sends a user message in a given session.

        1. Loads session history from the store.
        2. Calls pipeline.query_with_history() with the full history.
        3. Persists both the user turn and the assistant reply.
        4. Returns the assistant reply string.
        """
        # Validate session exists
        session = self.store.get_session(session_id)
        if session is None:
            raise ValueError(
                f"Session '{session_id}' does not exist. "
                "Create one first with SessionStore.create_session()."
            )

        history = self.store.get_history(session_id)

        # Call the history-aware query on the pipeline
        reply = self.pipeline.query_with_history(user_message, history)

        # Persist both turns
        self.store.append_message(session_id, role="human", content=user_message)
        self.store.append_message(session_id, role="assistant", content=reply)

        return reply
