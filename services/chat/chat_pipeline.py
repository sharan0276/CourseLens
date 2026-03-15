import os
from typing import Generator, List

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

from services.chat.chat_history import ChatHistoryStore
from domain.chat_session import ChatSession
from services.rag.retrieval_service import RetrievalService
from services.rag.chroma_retriever import VectorStoreManager

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
        embeddings,
        history_store: ChatHistoryStore,
        llm,
        mode: str = "general",
        search_type: str = "similarity",
        k: int = 5,
        persist_dir: str = "CourseLens_data/chroma_db",
        collection_name: str = "course_lens"
    ):
        self.vector_store = VectorStoreManager(
            embeddings_model=embeddings,
            persist_directory=persist_dir,
            collection_name=collection_name
        )
        self.history_store = history_store
        self.llm = llm
        self.mode = mode
        self.search_type = search_type
        self.k = k

        # Advanced RetrievalService (replaces raw vector store retrieve)
        self.retrieval_service = RetrievalService(
            vector_store_manager=self.vector_store,
            db_path=persist_dir,
            collection_name=collection_name,
            k=k
        )

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
                "You are a debugging assistant for a C++ programming course.\n"
                "Your role is to guide students to find the fix themselves — never give it to them directly.\n\n"
                "STRICT RULES — you must follow all of these:\n"
                "1. NEVER write corrected code. Do not rewrite, patch, or show a fixed version of the student's code.\n"
                "2. NEVER say things like \"change line X to Y\" or \"replace X with Y\".\n"
                "3. Instead, ask the student a question that leads them toward the bug.\n"
                "e.g. \"What do you think happens when i equals the length of the array?\"\n"
                "4. Give at most ONE hint per response. Do not over-explain.\n"
                "5. If the student asks \"just give me the answer\" or \"tell me the fix\", refuse politely\n"
                "and redirect with a guiding question.\n"
                "6. If the student is completely stuck after 3 turns, you may give a stronger hint\n"
                "but still no direct code fix.\n"
                "7. Acknowledge what the student got right before pointing out what's wrong.\n"
                "8. Always cite the most relevant slide number and source file at the end of your response.\n\n"
                "RESPONSE FORMAT — every response must follow this structure:\n"
                "- One sentence acknowledging the error type\n"
                "- One guiding question or observation pointing toward the bug\n"
                "- (Optional) One concept reminder if relevant to the error\n\n"
                "Context:\n{context}"
            )
        else:
            system_answer = (
                "You are an assistant for question-answering tasks based on course materials.\n"
                "Use the following pieces of retrieved context to answer the user's question.\n"
                "If you don't know the answer, just say that you don't know.\n"
                "Use ten sentences maximum and keep the answer concise.\n"
                "Every factual claim MUST be followed by a citation in the form [N]. If a claim draws from multiple sources, cite all of them: [1][3].\n"
                "At the end, always include a 'Sources Used' section listing every citation number you used with its source file and title.\n"
                "IMPORTANT: If a retrieved document contains 'Attached Images: <filename>', and the image is relevant to your answer, you MUST include it in your response using markdown syntax: `![Image Description](CourseLens_data/images/<filename>)`\n"
                "\nContext:\n{context}"
            )

        self._answer_prompt = ChatPromptTemplate.from_messages([
            ("system", system_answer),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_docs(self, docs: List[Document]) -> str:
        formatted_docs = []
        for doc in docs:
            source_file = doc.metadata.get("source_file", "Unknown")
            slide_number = doc.metadata.get("slide_number", "")
            title = doc.metadata.get("title", "")
            chunk_type = doc.metadata.get("chunk_type", "")
            image_filenames = doc.metadata.get("image_filenames", "")

            if chunk_type == "parent":
                citation = f"Source: {source_file}, Title: {title}"
            else:
                citation = f"Source: {source_file}, Title: {title}, Slide: {slide_number}"

            if image_filenames:
                image_filenames = image_filenames.replace(".emf", ".png")
                citation += f", Attached Images: {image_filenames}"

            formatted_docs.append(f"{citation}\n{doc.page_content}")
        
        return "\n\n".join(formatted_docs)

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
        session = self.history_store.load_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")

        lc_history = self._session_to_lc_history(session)

        # Condense history + new input into a retrieval-ready question
        standalone_q = self._condense_question(lc_history, user_input)

        # Retrieve relevant docs via the RetrievalService
        docs = self.retrieval_service.retrieve(standalone_q)
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
            reply = self._validate_response(reply, user_input)

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

        # Retrieve relevant docs via the RetrievalService
        docs = self.retrieval_service.retrieve(standalone_q)
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
            full_reply = self._validate_response(full_reply, user_input)

        session.add_message(role="user", content=user_input)
        session.add_message(role="assistant", content=full_reply)
        self.history_store.save_session(session)

    # ── Guardrail (coding mode) ────────────────────────────────────────────────

    def _contains_direct_fix(self, reply: str, student_input: str) -> bool:
        """Heuristic checks to detect if the model gave away the answer."""
        reply_lower = reply.lower()

        # Check 1: response contains a code block
        if "```" in reply:
            return True

        # Check 2: giveaway phrases
        giveaway_phrases = [
            "change line", "replace", "should be", "correct code",
            "fix is", "solution is", "here's the fix", "the answer is",
            "you need to write", "use this instead"
        ]
        if any(phrase in reply_lower for phrase in giveaway_phrases):
            return True

        # Check 3: significant overlap with student's submitted code lines
        student_lines = set(
            l.strip() for l in student_input.splitlines()
            if len(l.strip()) > 10
        )
        reply_lines = set(
            l.strip() for l in reply.splitlines()
            if len(l.strip()) > 10
        )
        if len(student_lines & reply_lines) >= 2:
            return True

        return False

    def _generate_fallback(self, student_input: str) -> str:
        """
        Uses the existing LLM to generate a Socratic fallback hint
        specific to the student's code and error, with no direct fix.
        """
        fallback_prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are a strict Socratic tutor. Your only job is to ask ONE guiding question "
             "that helps a student find their bug. You must NEVER include code, fixes, or direct answers."),
            ("human", 
             "A student submitted this input and got a bad response:\n\n{input}\n\n"
             "Write ONE short guiding question (1-2 sentences) specific to their code and error.")
        ])
        fallback_chain = fallback_prompt | self.llm | StrOutputParser()
        return fallback_chain.invoke({"input": student_input})

    def _validate_response(self, reply: str, student_input: str) -> str:
        """If a direct fix is detected, generate a Socratic fallback."""
        if self._contains_direct_fix(reply, student_input):
            return self._generate_fallback(student_input)
        return reply

