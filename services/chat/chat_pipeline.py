import os
from typing import Generator, List

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

from services.chat.chat_history import ChatHistoryStore
from domain.chat_session import ChatSession
from services.rag.retrieval_service import RetrievalService
from services.rag.chroma_retriever import VectorStoreManager
from services.rag.web_content_scraper import WebContentScraper
from services.chat.query_classifier import QueryClassifier
from services.chat.anchor_retrieval import AnchorRetrieval
from services.chat.socratic_engine import SocraticEngine
from services.chat.summarization_engine import SummarizationEngine
from services.chat.query_router import QueryRouter
from services.chat.citation_utils import add_sources_footer


class ChatPipeline:
    """
    Wraps the RAG vector store with multi-turn conversational memory.
    History is loaded from / persisted to ChatHistoryStore (JSON on disk).

    Each call to `chat()`:
      1. Loads the session history from disk.
      2. Builds a "context-aware" question by condensing the history + new input.
      3. Routes through QueryRouter — Direct, Socratic, or Out of Scope.
      4. Persists both the user message and assistant reply back to disk.
    """

    def __init__(
        self,
        embeddings,
        history_store: ChatHistoryStore,
        llm,
        flash_llm,  # added: lightweight model for classification and reply assessment
        mode: str = "general",
        search_type: str = "similarity",
        k: int = 5,
        persist_dir: str = "CourseLens_data/chroma_db",
        collection_name: str = "course_lens"
    ):
        from services.rag.bm25_retriever import BM25Manager
        self.vector_store = VectorStoreManager(
            embeddings_model=embeddings,
            persist_directory=persist_dir,
            collection_name=collection_name
        )
        self.bm25_manager = BM25Manager()
        self.history_store = history_store
        self.llm = llm
        self.flash_llm = flash_llm  # added: stored so QueryRouter components can use it
        self.mode = mode
        self.search_type = search_type
        self.k = k

        # retrieval service — shared by direct path and anchor retrieval
        # unchanged from before — QueryRouter reuses the same instance for both paths
        self.retrieval_service = RetrievalService(
            vector_store_manager=self.vector_store,
            bm25_manager=self.bm25_manager,
            db_path=persist_dir,
            collection_name=collection_name,
            k=k
        )

        # Web content scraper — fetches supplementary content from GFG, W3Schools, LearnCpp
        # distinguish_sources=False → blended output (set True for labeled output)
        self.web_scraper = WebContentScraper(distinguish_sources=False)

        # added: Socratic components constructed once here and injected into QueryRouter
        # AnchorRetrieval reuses the existing RetrievalService — no new DB connection
        anchor_retrieval = AnchorRetrieval(
            retrieval_service=self.retrieval_service,
            web_scraper=self.web_scraper
        )
        classifier = QueryClassifier(llm=flash_llm)
        socratic_engine = SocraticEngine(
            llm=llm,
            flash_llm=flash_llm,
            anchor_retrieval=anchor_retrieval
        )
        summarization_engine = SummarizationEngine(
            llm=llm,
            retrieval_service=self.retrieval_service
        )

        # added: QueryRouter wires classifier, anchor retrieval, and socratic engine
        # replaces the inline retrieval call that previously lived in chat() and chat_stream()
        self.query_router = QueryRouter(
            classifier=classifier,
            anchor_retrieval=anchor_retrieval,
            socratic_engine=socratic_engine,
            summarization_engine=summarization_engine
        )

        # ── Prompts ──────────────────────────────────────────────────────────

        # Step 1: answer using retrieved context — Direct path only
        if mode == "coding":
            system_answer = (
                "You are a debugging assistant for a C++ programming course.\n"
                "You have access to the conversation history. Use it to understand what the student has already tried, previous hints you have given, and the evolving context of their problem.\n"
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
                "8. EXCEPTION: If the student asks if their code is completely correct, and you review it and find absolutely ZERO bugs, you MUST explicitly validate their code ('Your code is completely correct!') and bypass all Socratic rules.\n"
                "9. Always cite the most relevant slide number and source file at the end of your response.\n"
                "10. If any part of your answer draws from a 'Web Reference' in the context, cite it using the exact format [SiteName: Title] (e.g., [GeeksForGeeks: Pointers in C++]). List web references along with slide citations in your Sources Used section.\n\n"
                "RESPONSE FORMAT — every response must follow this structure:\n"
                "- One sentence acknowledging the error type\n"
                "- One guiding question or observation pointing toward the bug\n"
                "- (Optional) One concept reminder if relevant to the error\n\n"
                "Context:\n{context}"
            )
        else:
            system_answer = (
                "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course.\n"
                "You have access to the conversation history. Use it to interpret the user's current question in context.\n"
                "Use the following pieces of retrieved context to answer the user's question.\n"
                "The context contains course slides and web references (LearnCpp, GFG, W3Schools). Use BOTH for a comprehensive answer.\n"
                "You may synthesize foundational concepts or analogies to clarify technical terms.\n"
                "If the context chunks do not contain enough information, just say that you don't know.\n"
                "Use fifteen sentences maximum.\n\n" # FIX: Increased sentence limit from 10 to 15
                "COMPREHENSIVENESS RULE: If the user's question has multiple answers or components listed in the context, you MUST list ALL of them. For each item listed, provide a brief explanation of 'why' or 'how' it is relevant based on the material.\n\n" # FIX: Ensured comprehensive listing and explanation
                "CITATION RULES:\n"
                "1. Use [filename, Slide N] for slides (e.g., [chap01.pptx, Slide 7]) and [SiteName: Title] for web (e.g., [LearnCpp: Arrays]).\n"
                "2. MANDATORY: Do NOT create your own 'Sources Used' or 'References' section at the end. Only use inline brackets. Our system will generate the list automatically.\n"
                "3. REDUNDANCY RULE: Only incorporate web information if it adds specific technical detail NOT found in the slides.\n"
                "4. META-QUERY OVERRIDE: If the user explicitly asks *where* a concept is taught, naturally state the filename/slide number in plain text without brackets.\n"
                "5. STRICT IGNORANCE: If the student uses a symbol, operator, or concept (e.g., `==`) that is NOT defined in your provided context chunks, you MUST NOT explain it using your prior knowledge. State that the concept is beyond the current material, and ONLY correct them using concepts that ARE in the context (like explaining `=` for assignment).\n\n"
                "CRITICAL: If a retrieved document contains 'Attached Images', include it: `![Description](CourseLens_data/images/<filename>)`.\n"
                "\nContext:\n{context}"
            )
            
        self._conversational_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a friendly C++ course assistant. Respond naturally to the user's greeting, pleasantry, or meta-question about the conversation history. Answer using the chat history provided. Do not invent course material."),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        self._answer_prompt = ChatPromptTemplate.from_messages([
            ("system", system_answer),
            MessagesPlaceholder("history"),
            ("human", "Please completely address the following student query or provided context: {input}"),
        ])

        # Step 3: Summarize history
        self._summarize_history_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a helpful assistant that summarizes conversation history. "
             "You MUST preserve any code snippets or exact syntax exactly as they were provided in the original conversation using markdown block formatting. Do not summarize or alter code blocks."),
            ("human", 
             "Given the previous summary and the new conversation lines, provide a concise updated summary "
             "of the entire conversation up to this point. Focus on key facts, questions asked, and answers given."
             "\n\nPrevious Summary:\n{previous_summary}\n\nNew Conversation:\n{new_lines}"),
        ])

        # Added: Condense history + current input into a standalone question
        self._condense_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "Given a conversation history and a follow-up user input, rephrase the follow-up into a "
             "standalone question that can be understood without the rest of the history.\n"
             "If the input is already a standalone question, return it as-is.\n"
             "Do NOT answer the question — only rephrase it."),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ])

    def _conversational_answer(self, session: ChatSession, standalone_q: str, user_input: str) -> str:
        lc_history = self._session_to_lc_history(session)
        answer_chain = self._conversational_prompt | self.llm | StrOutputParser()
        return answer_chain.invoke({"history": lc_history, "input": user_input})


    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_docs(self, docs: List[Document]) -> str:
        course_docs = []
        web_docs = []

        for doc in docs:
            source_type = doc.metadata.get("source_type", "")

            if source_type == "web":
                site = doc.metadata.get("source_site", "Web")
                title = doc.metadata.get("title", "")
                url = doc.metadata.get("source_file", "")
                citation = f"[{site}: {title}]\nURL: {url}"
                web_docs.append(f"{citation}\n{doc.page_content}")
                continue

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

            course_docs.append(f"{citation}\n{doc.page_content}")

        # Build context with clear section separation
        sections = []
        if course_docs:
            sections.append("=== COURSE MATERIAL ===\n" + "\n\n".join(course_docs))
        if web_docs:
            sections.append("=== WEB REFERENCES (You MUST cite these using [SiteName: Title] format) ===\n" + "\n\n".join(web_docs))

        return "\n\n".join(sections)

    def _session_to_lc_history(self, session: ChatSession) -> list:
        """Convert ChatSession messages to LangChain message objects, including summary if present."""
        lc_msgs = []
        if session.history_summary:
            # We pass the summary as an AIMessage so the LLM feels ownership
            # over the previous code blocks and facts, enabling it to reference them naturally.
            lc_msgs.append(AIMessage(content=f"[Conversation Memory: Summary of our dialogue so far]\n\n{session.history_summary}"))
            
        for msg in session.messages[session.summary_index:]:
            if msg.role == "user":
                lc_msgs.append(HumanMessage(content=msg.content))
            else:
                lc_msgs.append(AIMessage(content=msg.content))
        return lc_msgs

    def _update_session_summary(self, session: ChatSession):
        """Summarizes unsummarized messages dynamically."""
        if session.in_socratic_loop():
            # Defer summarization until the loop concludes
            return

        # Summarize to the very end
        if len(session.messages) > session.summary_index:
            end_idx = len(session.messages)
            msgs_to_summarize = session.messages[session.summary_index:end_idx]
            
            new_lines = ""
            for m in msgs_to_summarize:
                role = "User" if m.role == "user" else "Assistant"
                new_lines += f"{role}: {m.content}\n"
                
            chain = self._summarize_history_prompt | self.flash_llm | StrOutputParser()
            new_summary = chain.invoke({
                "previous_summary": session.history_summary or "No previous summary.",
                "new_lines": new_lines
            })
            
            session.history_summary = new_summary
            session.summary_index = end_idx

    def _condense_question(self, history: list, user_input: str) -> str:
        """
        Rephrases follow-up input into a standalone question using history.
        """
        if not history:
            return user_input
        
        # User visibility: Print the history being shared with the condenser
        print("\n── Condenser History ────────────────────────────────")
        for msg in history:
            role = "U" if isinstance(msg, HumanMessage) else "A"
            content = msg.content.replace('\n', ' ')
            print(f"[{role}] {content}")
        print("─────────────────────────────────────────────────────")

        chain = self._condense_prompt | self.llm | StrOutputParser()
        return chain.invoke({"history": history, "input": user_input})

    def _direct_answer(self, session: ChatSession, standalone_q: str, user_input: str, topics: List[str] = None, lecture_number: int = None) -> str:
        """
        Runs the existing direct RAG chain, enriched with web content.
        """
        lc_history = self._session_to_lc_history(session)
        # Fix retrieval leak: pass the lecture_number filter into the search
        docs = self.retrieval_service.retrieve(standalone_q, lecture_number=lecture_number)

        # Enrich with web content if topics were identified
        if topics:
            web_docs = self.web_scraper.search_topics(topics)
            docs = docs + web_docs  # course material first, web content after

        context = self._format_docs(docs)
        
        # User visibility: Show which documents are being sent for answering
        print("\n── Context Documents ────────────────────────────────")
        for i, d in enumerate(docs, 1):
            # Check all common source metadata keys used across different retrievers
            m = d.metadata
            source_raw = (
                m.get('source_site') or     # Web
                m.get('source_file') or     # Slides
                m.get('source') or          # Standard
                m.get('file_path') or       # Potential alternatives
                m.get('filename') or 
                'Unknown'
            )
            source = os.path.basename(source_raw) if ('/' in source_raw or '\\' in source_raw) else source_raw
            title = m.get('title', 'No Title')
            print(f"[{i}] {source} - {title}")
        print("─────────────────────────────────────────────────────")

        answer_chain = self._answer_prompt | self.llm | StrOutputParser()
        
        # FOCUS SHIFT: Use standalone_q for the final answer instead of vague user_input
        reply = answer_chain.invoke({
            "history": lc_history,
            "input": standalone_q,
            "context": context,
        })
        if self.mode == "coding":
            reply = self._validate_response(reply, standalone_q)
        return reply

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(self, session_id: str, user_input: str, lecture_number: int = None) -> str:
        """
        Single-turn chat that is multi-turn aware.
        Loads history → condenses question → routes → saves.

        Updated: inline retrieval and answer chain replaced with QueryRouter.route()
        ChatPipeline now only owns session lifecycle — load, condense, save.
        Routing and response generation are fully delegated to QueryRouter.
        """
        session = self.history_store.load_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.in_socratic_loop():
            standalone_q = user_input
        else:
            lc_history = self._session_to_lc_history(session)
            standalone_q = self._condense_question(lc_history, user_input)
            if standalone_q != user_input:
                print(f"\n[Condenser] Condensed query: {standalone_q}")

        # updated: single QueryRouter call replaces inline retrieve → format → answer chain
        # direct_handler lambda passes Direct path back to _direct_answer
        # without QueryRouter needing to know about session or history internals
        reply = self.query_router.route(
            session=session,
            user_input=user_input,
            standalone_q=standalone_q,
            lecture_number=lecture_number,
            direct_handler=lambda sq, ui, topics: self._direct_answer(session, sq, ui, topics, lecture_number),
            conversational_handler=lambda sq, ui: self._conversational_answer(session, sq, ui)
        )

        session.add_message(role="user", content=user_input)
        session.add_message(role="assistant", content=reply)
        self._update_session_summary(session)
        self.history_store.save_session(session)

        # Apply citation formatting before returning to UI/CLI
        # For Socratic Stage 2 and 3, skip the numbered bibliography / footer
        if session.ta_stage in [2, 3]:
            return reply
        return add_sources_footer(reply)

    def chat_stream(self, session_id: str, user_input: str, lecture_number: int = None) -> Generator[str, None, None]:
        """
        Streaming variant — yields chunks for Direct path.

        Updated: Socratic and Out of Scope paths cannot stream token by token
        because routing decisions happen mid-response. These paths return a full
        string and yield it once instead. Direct path streams normally as before.
        _should_use_socratic() pre-classifies before streaming starts to avoid
        switching paths mid-response.
        """
        session = self.history_store.load_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")

        if session.in_socratic_loop():
            standalone_q = user_input
        else:
            lc_history = self._session_to_lc_history(session)
            standalone_q = self._condense_question(lc_history, user_input)
            if standalone_q != user_input:
                print(f"\n[Condenser] Condensed query: {standalone_q}")

        # added: pre-check routes Socratic and Out of Scope through QueryRouter
        # yielding the full reply at once rather than streaming token by token
        if session.in_socratic_loop() or self._should_use_socratic(standalone_q, lecture_number):
            reply = self.query_router.route(
                session=session,
                user_input=user_input,
                standalone_q=standalone_q,
                lecture_number=lecture_number,
                direct_handler=lambda sq, ui, topics: self._direct_answer(session, sq, ui, topics, lecture_number),
                conversational_handler=lambda sq, ui: self._conversational_answer(session, sq, ui)
            )
            session.add_message(role="user", content=user_input)
            session.add_message(role="assistant", content=reply)
            self._update_session_summary(session)
            self.history_store.save_session(session)
            
            # Apply citation formatting to Socratic/Out-of-Scope responses
            # For Socratic Stage 2 and 3, skip the numbered bibliography / footer
            if session.ta_stage in [2, 3]:
                yield reply
            else:
                yield add_sources_footer(reply)
            return

        # Direct path — streams token by token, enriched with web content
        lc_history = self._session_to_lc_history(session)
        docs = self.retrieval_service.retrieve(standalone_q, lecture_number=lecture_number)

        # Enrich streaming direct path with web content
        stream_result = self.query_router.classifier.classify(standalone_q, lecture_number)
        if stream_result.selected_topics:
            web_docs = self.web_scraper.search_topics(stream_result.selected_topics)
            docs = docs + web_docs
        context = self._format_docs(docs)

        # User visibility: Show which documents are being sent for answering (Streaming)
        print("\n── Context Documents (Streaming) ────────────────────")
        for i, d in enumerate(docs, 1):
            m = d.metadata
            source_raw = (
                m.get('source_site') or 
                m.get('source_file') or 
                m.get('source') or 
                m.get('file_path') or 
                m.get('filename') or 
                'Unknown'
            )
            source = os.path.basename(source_raw) if ('/' in source_raw or '\\' in source_raw) else source_raw
            title = m.get('title', 'No Title')
            print(f"[{i}] {source} - {title}")
        print("─────────────────────────────────────────────────────")

        answer_chain = self._answer_prompt | self.llm | StrOutputParser()

        full_reply = ""
        # FOCUS SHIFT: Use standalone_q for the final streaming response
        for chunk in answer_chain.stream({
            "history": lc_history,
            "input": standalone_q,
            "context": context,
        }):
            full_reply += chunk
            yield chunk

        # Append bibliography at the end of the stream if citations exist
        formatted_full = add_sources_footer(full_reply)
        if "Sources Used:" in formatted_full:
            bibliography = formatted_full.split("Sources Used:")[1]
            yield f"\n\nSources Used:{bibliography}"

        if self.mode == "coding":
            full_reply = self._validate_response(full_reply, standalone_q)

        session.add_message(role="user", content=user_input)
        session.add_message(role="assistant", content=full_reply)
        self._update_session_summary(session)
        self.history_store.save_session(session)

    def _should_use_socratic(self, standalone_q: str, lecture_number: int) -> bool:
        """
        Added: pre-classification check for chat_stream only.
        Streaming cannot switch paths mid-response so this decides upfront
        whether the query will go to Socratic or Out of Scope before any
        tokens start flowing. Runs a Flash classification call.
        Only called when not already in an active Socratic loop.
        """
        result = self.query_router.classifier.classify(standalone_q, lecture_number)
        return result.query_type.value in ["SOCRATIC", "OUT_OF_SCOPE", "SUMMARIZE_LECTURE"]

    # ── Guardrail (coding mode) ────────────────────────────────────────────────

    def _contains_direct_fix(self, reply: str, student_input: str) -> bool:
        """Heuristic checks to detect if the model gave away the answer."""
        reply_lower = reply.lower()

        if "```" in reply:
            return True

        giveaway_phrases = [
            "change line", "replace", "should be", "correct code",
            "fix is", "solution is", "here's the fix", "the answer is",
            "you need to write", "use this instead"
        ]
        if any(phrase in reply_lower for phrase in giveaway_phrases):
            return True

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
        """Generates a Socratic fallback hint when guardrail fires."""
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