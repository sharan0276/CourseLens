import os
from typing import List, Generator, Dict
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

from services.rag.loader import JSONSlideLoader
from services.rag.vector_store import VectorStoreManager

class RAGPipelineCoding:
    def __init__(self, llm: BaseChatModel, embeddings: Embeddings, data_dir: str = "CourseLens_data/processed_data/",
                 persist_dir: str = "CourseLens_data/chroma_db", search_type: str = "similarity"):
        self.llm = llm
        self.embeddings = embeddings

        self.loader = JSONSlideLoader(data_dir=data_dir)
        self.vector_store = VectorStoreManager(embeddings_model=self.embeddings, persist_directory=persist_dir)
        self.search_type = search_type

        system_prompt = (            
                    """You are a debugging assistant for a C++ programming course.
                Your role is to guide students to find the fix themselves — never give it to them directly.

                STRICT RULES — you must follow all of these:
                1. NEVER write corrected code. Do not rewrite, patch, or show a fixed version of the student's code.
                2. NEVER say things like "change line X to Y" or "replace X with Y".
                3. Instead, ask the student a question that leads them toward the bug.
                e.g. "What do you think happens when i equals the length of the array?"
                4. Give at most ONE hint per response. Do not over-explain.
                5. If the student asks "just give me the answer" or "tell me the fix", refuse politely
                and redirect with a guiding question.
                6. If the student is completely stuck after 3 turns, you may give a stronger hint
                but still no direct code fix.
                7. Acknowledge what the student got right before pointing out what's wrong.
                8. Always cite the most relevant slide number and source file at the end of your response.
                    Course Material Context:.

                RESPONSE FORMAT — every response must follow this structure:
                - One sentence acknowledging the error type
                - One guiding question or observation pointing toward the bug
                - (Optional) One concept reminder if relevant to the error

                {context} """
        )

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        self.chain = self._build_chain()

    # ── Level 2 Guardrail Helpers ─────────────────────────────────────────────

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

    # ── Chain Helpers ─────────────────────────────────────────────────────────

    def _format_docs(self, docs: List[Document]) -> str:
        """Formats retrieved course slide chunks with citations for model input."""
        formatted_docs = []
        for doc in docs:
            source_file = doc.metadata.get("source_file", "Unknown")
            slide_number = doc.metadata.get("slide_number", "")
            title = doc.metadata.get("title", "")
            chunk_type = doc.metadata.get("chunk_type", "")

            if chunk_type == "parent":
                citation = f"Source: {source_file}, Title: {title}"
            else:
                citation = f"Source: {source_file}, Title: {title}, Slide: {slide_number}"

            formatted_docs.append(f"{citation}\n{doc.page_content}")

        return "\n\n".join(formatted_docs)

    def _build_chain(self):
        retriever = self.vector_store.get_retriever(search_type=self.search_type, k=5)

        rag_chain = (
            {"context": retriever | self._format_docs, "input": RunnablePassthrough()}
            | self.prompt
            | self.llm
            | StrOutputParser()
        )
        return rag_chain

    # ── Public Methods ────────────────────────────────────────────────────────

    def ingest_data(self) -> None:
        """Loads data from the JSON directory and stores it in the vector DB."""
        print("Loading documents using ChunkBuilder...")
        docs = self.loader.load()
        if docs:
            print(f"Loaded {len(docs)} documents. Adding to vector store...")
            self.vector_store.add_documents(docs)
            print("Ingestion complete.")
        else:
            print("No documents found to ingest.")

    def query(self, question: str) -> str:
        """Queries the RAG pipeline, validates, and returns the answer."""
        reply = self.chain.invoke(question)
        return self._validate_response(reply, question)  # ← Level 2 here

    def query_stream(self, question: str) -> Generator[str, None, None]:
        """Queries the RAG pipeline, validates, then streams the answer."""
        # Stream the full response first, then validate before yielding
        full_reply = "".join(chunk for chunk in self.chain.stream(question))
        validated  = self._validate_response(full_reply, question)  # ← Level 2 here
        yield validated

    # ── History-aware (session) methods ──────────────────────────────────────

    def _build_history_chain_coding(self):
        """Builds a Socratic history-aware chain using MessagesPlaceholder."""
        retriever = self.vector_store.get_retriever(search_type=self.search_type, k=5)

        system_prompt = (
            "You are a debugging assistant for a C++ programming course.\n"
            "Your role is to guide students to find the fix themselves — never give it to them directly.\n"
            "STRICT RULES:\n"
            "1. NEVER write corrected code.\n"
            "2. Ask guiding questions instead of giving direct answers.\n"
            "3. Give at most ONE hint per response.\n"
            "4. Acknowledge what the student got right before pointing out what's wrong.\n"
            "Use the conversation history to track the student's progress.\n"
            "\nCourse Material Context:\n{context}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
        ])

        def retrieve_and_format(inputs):
            docs = retriever.invoke(inputs["input"])
            return self._format_docs(docs)

        chain = (
            {
                "context": RunnableLambda(retrieve_and_format),
                "input": RunnablePassthrough(),
                "chat_history": RunnablePassthrough(),
            }
            | prompt
            | self.llm
            | StrOutputParser()
        )
        return chain

    @staticmethod
    def _to_lc_messages(history: List[Dict[str, str]]):
        """Converts stored {role, content} dicts to LangChain message objects."""
        msgs = []
        for msg in history:
            if msg["role"] == "human":
                msgs.append(HumanMessage(content=msg["content"]))
            else:
                msgs.append(AIMessage(content=msg["content"]))
        return msgs

    def query_with_history(self, question: str, history: List[Dict[str, str]]) -> str:
        """
        Queries the Socratic coding pipeline using prior conversation history.
        Guardrails (no direct code fix) are preserved.

        Args:
            question: The new student message.
            history: List of {"role": "human"|"assistant", "content": str} dicts.

        Returns:
            Validated Socratic response string.
        """
        if not hasattr(self, "_history_chain_coding"):
            self._history_chain_coding = self._build_history_chain_coding()

        lc_history = self._to_lc_messages(history)
        reply = self._history_chain_coding.invoke({
            "input": question,
            "chat_history": lc_history,
        })
        return self._validate_response(reply, question)