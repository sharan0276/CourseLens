from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from domain.chat_session import ChatSession
from services.chat.query_classifier import QueryClassifier, QueryType
from services.chat.anchor_retrieval import AnchorRetrieval
from services.chat.socratic_engine import SocraticEngine


class QueryRouter:
    """
    Thin orchestration layer — the single entry point for every student query.

    Routing paths:
      DIRECT        — condense question, retrieve, answer via existing RAG chain
      SOCRATIC      — classify, select topics, anchor retrieval, enter stage loop
      OUT_OF_SCOPE  — check future lectures, redirect cleanly, no retrieval

    Also handles stale loop detection — if a student abandons a Socratic loop
    mid-way and asks something Direct or Out of Scope, state is reset first.
    """

    def __init__(
        self,
        classifier: QueryClassifier,
        anchor_retrieval: AnchorRetrieval,
        socratic_engine: SocraticEngine,
    ):
        self.classifier = classifier
        self.anchor_retrieval = anchor_retrieval
        self.socratic_engine = socratic_engine

    def route(
        self,
        session: ChatSession,
        user_input: str,
        standalone_q: str,
        lecture_number: int,
        direct_handler,
    ) -> str:
        """
        Routes the query to the correct path and returns the assistant reply.

        Args:
            session        — current ChatSession with all state
            user_input     — raw student message as typed
            standalone_q   — condensed standalone question from ChatPipeline
            lecture_number — student's current lecture for progressive disclosure
            direct_handler — callable that runs the existing direct RAG chain
                             signature: direct_handler(standalone_q, user_input) -> str
        """

        # ── Mid-Loop Direct Passthrough ──────────────────────────────────────────────
        # If the student is actively engaged in a Socratic loop, bypass the generic 
        # router classifier. The Socratic Engine's Flash Assessor is infinitely better 
        # equipped to handle tracking conversational answers, topic changes, and distractions.
        if session.in_socratic_loop():
            return self.socratic_engine.respond(session, user_input)

        # ── Fresh query — classify and route ─────────────────────────────────
        result = self.classifier.classify(standalone_q, lecture_number)

        if result.query_type == QueryType.OUT_OF_SCOPE:
            print("\n[Router] Routing to Out Of Scope handler")
            # check future lectures before redirecting
            return self.socratic_engine.respond_out_of_scope(
                user_input=user_input,
                selected_topics=result.selected_topics,
                lecture_number=lecture_number
            )

        if result.query_type == QueryType.SOCRATIC:
            print("\n[Router] Routing to Socratic Engine")
            # anchor retrieval once — stores chunk IDs in session
            self.anchor_retrieval.anchor(
                session=session,
                topics=result.selected_topics,
                lecture_number=lecture_number
            )
            # start the Socratic loop state on the session
            session.start_socratic_loop(
                query=user_input,
                chunk_ids=session.anchored_chunk_ids,
                topics=result.selected_topics
            )
            # respond with stage 1 locating question
            return self.socratic_engine.respond(
                session=session,
                user_input=user_input
            )

        # DIRECT — pass to existing RAG chain via the handler callable
        print("\n[Router] Routing to Direct Answer")
        return direct_handler(standalone_q, user_input)