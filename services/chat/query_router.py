from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from domain.chat_session import ChatSession
from services.chat.query_classifier import QueryClassifier, QueryType
from services.chat.anchor_retrieval import AnchorRetrieval
from services.chat.socratic_engine import SocraticEngine
from services.chat.summarization_engine import SummarizationEngine


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
        summarization_engine: SummarizationEngine,
    ):
        self.classifier = classifier
        self.anchor_retrieval = anchor_retrieval
        self.socratic_engine = socratic_engine
        self.summarization_engine = summarization_engine

    def route(
        self,
        session: ChatSession,
        user_input: str,
        standalone_q: str,
        lecture_number: int,
        direct_handler,
        conversational_handler,
    ) -> str:
        """
        Routes the query to the correct path and returns the assistant reply.

        Args:
            session        — current ChatSession with all state
            user_input     — raw student message as typed
            standalone_q   — condensed standalone question from ChatPipeline
            lecture_number — student's current lecture for progressive disclosure
            direct_handler — callable that runs the existing direct RAG chain
                             signature: direct_handler(standalone_q, user_input, topics) -> str
        """

        # ── Escape signal check — fast-track to Stage 4 if student asks for help ──
        # Must run before Socratic loop check so it can override mid-loop behaviour.
        _ESCAPE_SIGNALS = (
            "just tell me", "can you just explain", "skip to explanation",
            "skip", "i am still confused", "just explain it",
        )
        ui_lower = user_input.strip().lower()
        if session.in_socratic_loop() and any(ui_lower.startswith(sig) for sig in _ESCAPE_SIGNALS):
            print("\n[Router] Escape signal detected — fast-tracking to Stage 4 debrief")
            session.ta_stage = 4
            return self.socratic_engine.respond(session, user_input)

        # ── Mid-Loop Direct Passthrough ───────────────────────────────────────
        if session.in_socratic_loop():
            return self.socratic_engine.respond(session, user_input)

        # ── Deterministic prefix checks on raw user_input ────────────────────
        # Run BEFORE classify() so condensing can't strip question starters.
        if any(ui_lower.startswith(p) for p in self.classifier._DIRECT_PREFIXES):
            print("\n[Router] Raw input prefix → forcing Direct Answer")
            # Still classify to extract topics for web content enrichment
            prefix_result = self.classifier.classify(standalone_q, lecture_number)
            prefix_topics = prefix_result.selected_topics if prefix_result.selected_topics else []
            return direct_handler(standalone_q, user_input, prefix_topics)

        if any(ui_lower.startswith(p) for p in self.classifier._SOCRATIC_PREFIXES):
            print("\n[Router] Raw input prefix → forcing Socratic Engine")
            result = self.classifier.classify(standalone_q, lecture_number)
            topics = result.selected_topics
            self.anchor_retrieval.anchor(
                session=session,
                topics=topics,
                lecture_number=lecture_number
            )
            session.start_socratic_loop(
                query=user_input,
                chunk_ids=session.anchored_chunk_ids,
                topics=topics
            )
            return self.socratic_engine.respond(session=session, user_input=user_input)

        # ── Fresh query — classify and route ─────────────────────────────────
        result = self.classifier.classify(standalone_q, lecture_number)
        topics = result.selected_topics if result.selected_topics else []

        if result.query_type == QueryType.SUMMARIZE_LECTURE:
            print("\n[Router] Routing to Summarization Engine")
            target = result.target_lecture if result.target_lecture is not None else lecture_number
            return self.summarization_engine.summarize(
                session=session,
                lecture_number=target,
                user_input=user_input
            )

        if result.query_type == QueryType.OUT_OF_SCOPE:
            print("\n[Router] Routing to Out Of Scope handler")
            return self.socratic_engine.respond_out_of_scope(
                user_input=user_input,
                selected_topics=result.selected_topics,
                lecture_number=lecture_number
            )

        if result.query_type == QueryType.SOCRATIC:
            print("\n[Router] Routing to Socratic Engine")
            self.anchor_retrieval.anchor(
                session=session,
                topics=result.selected_topics,
                lecture_number=lecture_number
            )
            session.start_socratic_loop(
                query=user_input,
                chunk_ids=session.anchored_chunk_ids,
                topics=result.selected_topics
            )
            return self.socratic_engine.respond(session=session, user_input=user_input)

        # DIRECT — pass to existing RAG chain via the handler callable
        print("\n[Router] Routing to Direct Answer")
        return direct_handler(standalone_q, user_input, topics)