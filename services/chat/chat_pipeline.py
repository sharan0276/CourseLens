import os
from typing import Generator, List

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

from services.chat.chat_history import ChatHistoryStore
from domain.chat_session import ChatSession


class ChatPipeline:
    """
    Wraps the RAG vector store with multi-turn conversational memory.
    History is loaded from / persisted to ChatHistoryStore (JSON on disk).

    Each call to `chat()`:
      1. Loads the session history from disk.
      2. Builds a "context-aware" question by condensing the history + new input.
      3. Runs the RAG retrieval chain.
      4. Persists both the user message and assistant reply back to disk.
    """

    def __init__(
        self,
        vector_store_manager,
        history_store: ChatHistoryStore,
        llm,
        mode: str = "general",
        search_type: str = "similarity",
        k: int = 5,
    ):
        self.vector_store = vector_store_manager
        self.history_store = history_store
        self.llm = llm
        self.mode = mode
        self.search_type = search_type
        self.k = k

        # Retriever
        self.retriever = self.vector_store.get_retriever(search_type=search_type, k=k)

        # ── Prompts ──────────────────────────────────────────────────────────

        # Step 1: condense history + new question → a standalone question
        self._condense_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "Given the conversation history and a follow-up message, "
             "rephrase the follow-up message into a standalone question "
             "that can be understood without the history. "
             "Only return the rephrased question, nothing else."),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ])

        # Step 2: answer using retrieved context
        if mode == "coding":
            system_answer = (
                "You are a debugging assistant for a C++ programming course. "
                "Guide students to find bugs themselves — never give direct fixes or rewrite code. "
                "Ask ONE guiding question per turn. "
                "Use the retrieved course material below as context.\n\nContext:\n{context}"
            )
        else:
            system_answer = (
                "You are a helpful assistant for a university course. "
                "Answer the student's question using the retrieved course material below. "
                "Be concise (3-5 sentences). If you don't know, say so.\n\nContext:\n{context}"
            )

        self._answer_prompt = ChatPromptTemplate.from_messages([
            ("system", system_answer),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_docs(self, docs: List[Document]) -> str:
        formatted = []
        for doc in docs:
            src = doc.metadata.get("source_file", "")
            slide = doc.metadata.get("slide_number", "")
            title = doc.metadata.get("title", "")
            citation = f"[{src} | {title}" + (f" | Slide {slide}" if slide else "") + "]"
            formatted.append(f"{citation}\n{doc.page_content}")
        return "\n\n".join(formatted)

    def _session_to_lc_history(self, session: ChatSession) -> list:
        """Convert ChatSession messages to LangChain message objects."""
        lc_msgs = []
        for msg in session.messages:
            if msg.role == "user":
                lc_msgs.append(HumanMessage(content=msg.content))
            else:
                lc_msgs.append(AIMessage(content=msg.content))
        return lc_msgs

    def _condense_question(self, history: list, user_input: str) -> str:
        """
        If there's prior history, rephrase the user input into a standalone question.
        Otherwise just return it as-is (no need to call LLM).
        """
        if not history:
            return user_input
        chain = self._condense_prompt | self.llm | StrOutputParser()
        return chain.invoke({"history": history, "input": user_input})

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, session_id: str, user_input: str) -> str:
        """
        Single-turn chat that is multi-turn aware.
        Loads history → condenses question → retrieves → answers → saves.
        Returns the assistant's reply string.
        """
        # Load session (or fail fast with ValueError)
        session = self.history_store.load_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")

        lc_history = self._session_to_lc_history(session)

        # Condense history + new input into a retrieval-ready question
        standalone_q = self._condense_question(lc_history, user_input)

        # Retrieve relevant docs
        docs = self.retriever.invoke(standalone_q)
        context = self._format_docs(docs)

        # Generate the answer
        answer_chain = self._answer_prompt | self.llm | StrOutputParser()
        reply = answer_chain.invoke({
            "history": lc_history,
            "input": user_input,
            "context": context,
        })

        # Apply coding guardrail if needed
        if self.mode == "coding":
            reply = self._coding_guardrail(reply, user_input)

        # Persist both turns
        session.add_message(role="user", content=user_input)
        session.add_message(role="assistant", content=reply)
        self.history_store.save_session(session)

        return reply

    def chat_stream(self, session_id: str, user_input: str) -> Generator[str, None, None]:
        """
        Streaming variant — yields chunks then persists when complete.
        """
        session = self.history_store.load_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")

        lc_history = self._session_to_lc_history(session)
        standalone_q = self._condense_question(lc_history, user_input)

        docs = self.retriever.invoke(standalone_q)
        context = self._format_docs(docs)

        answer_chain = self._answer_prompt | self.llm | StrOutputParser()

        full_reply = ""
        for chunk in answer_chain.stream({
            "history": lc_history,
            "input": user_input,
            "context": context,
        }):
            full_reply += chunk
            yield chunk

        if self.mode == "coding":
            # For streaming + coding, we post-validate; if guardrail triggers,
            # we can't "un-stream" so we just note it in history.
            full_reply = self._coding_guardrail(full_reply, user_input)

        session.add_message(role="user", content=user_input)
        session.add_message(role="assistant", content=full_reply)
        self.history_store.save_session(session)

    # ── Guardrail (coding mode) ────────────────────────────────────────────────

    def _coding_guardrail(self, reply: str, student_input: str) -> str:
        """Refuse direct code fixes — re-generate a Socratic question instead."""
        giveaway_phrases = [
            "change line", "replace", "should be", "correct code",
            "fix is", "solution is", "here's the fix", "the answer is",
            "you need to write", "use this instead",
        ]
        reply_lower = reply.lower()
        direct_fix = (
            "```" in reply
            or any(p in reply_lower for p in giveaway_phrases)
        )
        if direct_fix:
            from langchain_core.prompts import ChatPromptTemplate as CPT
            fallback_prompt = CPT.from_messages([
                ("system",
                 "You are a strict Socratic tutor. Ask ONE guiding question "
                 "that helps the student find their bug. No code, no direct fixes."),
                ("human",
                 "A student submitted this and got a direct-answer response:\n\n{input}\n\n"
                 "Write ONE short guiding question (1-2 sentences)."),
            ])
            chain = fallback_prompt | self.llm | StrOutputParser()
            return chain.invoke({"input": student_input})
        return reply
