from typing import List, Optional
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

from domain.chat_session import ChatSession
from services.chat.anchor_retrieval import AnchorRetrieval
from config.syllabus_loader import SyllabusLoader


class ReplyAssessment:
    """Possible assessments of a student's reply to a Socratic stage."""
    LOCATED = "LOCATED"           # student correctly identified the concept area
    WRONG_DIRECTION = "WRONG_DIRECTION"  # student identified something but it's off
    NO_ATTEMPT = "NO_ATTEMPT"     # student is lost or said they don't know


class SocraticEngine:
    """
    Drives the 3-stage Socratic tutoring loop modeled on real TA pedagogy.

    Stage 1 — Locating question: probe what concept the student thinks this relates to
    Stage 2 — Lead: adapt based on Flash reply assessment, hint toward the answer
    Stage 3 — Push: final nudge, student should be able to reach the answer themselves
    Stage 4 — Direct answer: overflow only, drop all Socratic framing entirely

    Flash handles reply assessment between stages.
    The generation LLM handles all student-facing responses.
    """

    def __init__(self, llm, flash_llm, anchor_retrieval: AnchorRetrieval):
        self.llm = llm
        self.flash_llm = flash_llm
        self.anchor_retrieval = anchor_retrieval
        self.parser = StrOutputParser()

        # ── Reply Assessor Prompt (Flash) ─────────────────────────────────────
        # reads student reply to stage 1 and decides how to transition
        self._assessor_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are assessing a student's reply in a Socratic tutoring session.\n\n"
             "The original problem the student asked about: {active_problem_query}\n"
             "The relevant course topics: {selected_topics}\n\n"
             "Assess the student's reply as exactly one of:\n"
             "LOCATED — student correctly identified the concept area or topic\n"
             "WRONG_DIRECTION — student identified something but it is off or incomplete\n"
             "NO_ATTEMPT — student said they don't know, gave no answer, or is clearly lost\n\n"
             "Reply with ONLY the label. No explanation."),
            ("human", "{student_reply}")
        ])

        # ── Stage 1 Prompt — Locating Question ───────────────────────────────
        # never gives the answer — purely probes student self-location
        self._stage1_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a Socratic tutor for a C++ programming course.\n"
             "A student has asked a question that needs guided understanding.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Your job at this stage is to ask ONE open-ended locating question.\n"
             "The question should probe what concept or topic the student thinks this relates to.\n\n"
             "STRICT RULES:\n"
             "1. Do NOT answer the question\n"
             "2. Do NOT give any hints toward the answer\n"
             "3. Ask only ONE question\n"
             "4. Keep it short — one or two sentences maximum\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        # ── Stage 2 Prompt — Lead ─────────────────────────────────────────────
        # branches based on reply assessment — three distinct behaviors
        self._stage2_located_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a Socratic tutor for a C++ programming course.\n"
             "The student correctly identified the relevant concept area.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Acknowledge what they got right, then provide ONE specific hint or leading "
             "observation that points them toward the answer without giving it away.\n\n"
             "STRICT RULES:\n"
             "1. Do NOT give the full answer\n"
             "2. Guide them exactly ONE step forward, building firmly on what they already understand.\n"
             "3. Teach sequentially: always address foundational concepts before dependent steps.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        self._stage2_wrong_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a Socratic tutor for a C++ programming course.\n"
             "The student identified something but is heading in the wrong direction.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Briefly validate any correct reasoning, precisely correct their misconception, "
             "and provide exactly ONE hint to guide their next logical step.\n\n"
             "STRICT RULES:\n"
             "1. Do NOT give the full answer\n"
             "2. Correct the specific misconception, then give ONE hint toward the right path.\n"
             "3. Do not overwhelm — one correction + one hint only.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        self._stage2_no_attempt_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a Socratic tutor for a C++ programming course.\n"
             "The student is lost and could not locate the relevant concept.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Explain the foundational concept first using the course material, "
             "then bridge back to the student's original question.\n\n"
             "STRICT RULES:\n"
             "1. Keep the explanation brief — one short paragraph\n"
             "2. End by connecting back to the original question\n"
             "3. Do NOT give the full answer to the original question yet\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        # ── Stage 3 Prompt — Final Push ───────────────────────────────────────
        # student should be able to reach the answer from here
        self._stage3_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a Socratic tutor for a C++ programming course.\n"
             "The student is ready for the final push toward the answer.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Give the student actionable, specific, directional guidance that "
             "lets them reach the answer themselves. They should not need another hint after this.\n\n"
             "STRICT RULES:\n"
             "1. Still do NOT give the full answer directly\n"
             "2. Be specific and concrete — vague nudges are not helpful at this stage\n"
             "3. One or two sentences maximum\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        # ── Stage 4 Prompt — Direct Answer ───────────────────────────────────
        # overflow only — drop all Socratic framing entirely
        self._stage4_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a course assistant for a C++ programming course.\n"
             "Provide a complete, direct answer to the student's original question.\n\n"
             "Original question: {active_problem_query}\n\n"
             "Give a clear, complete answer grounded in the course material provided.\n"
             "Use ten sentences maximum. Cite sources at the end.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        # ── Out of Scope Prompt ───────────────────────────────────────────────
        # no retrieval, no stages — two sentence redirect back to course content
        self._out_of_scope_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a course assistant for a C++ programming course.\n"
             "The student has asked something outside the scope of this course.\n\n"
             "STRICT RULES:\n"
             "1. Do not attempt to answer the question\n"
             "2. Politely acknowledge it falls outside the course\n"
             "3. Redirect the student back to what CourseLens can help with\n"
             "4. Keep it to two sentences maximum — friendly, not dismissive"),
            ("human", "{input}")
        ])


        # ── Out of Scope Prompt — Future Lecture ─────────────────────────────
        # topic exists in the course but student hasn't reached it yet
        self._future_lecture_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a course assistant for a C++ programming course.\n"
             "The student has asked about a topic that is covered later in the course "
             "but they haven't reached it yet.\n\n"
             "The topic appears in: {future_lecture}\n\n"
             "STRICT RULES:\n"
             "1. Do not explain the topic — they haven't reached it yet\n"
             "2. Let them know it is coming up in the course\n"
             "3. Encourage them to keep it in mind for when they get there\n"
             "4. Keep it to two sentences maximum — encouraging, not dismissive"),
            ("human", "{input}")
        ])

    # ── Public API ────────────────────────────────────────────────────────────

    def respond(self, session: ChatSession, user_input: str) -> str:
        """
        Main entry point. Routes to the correct stage prompt based on session.ta_stage.
        Handles reply assessment and stage transitions automatically.
        Builds conversation history directly from session messages — no external input needed.
        """
        # fetch the anchored chunks for this loop — same set across all stages
        context_docs = self.anchor_retrieval.fetch_anchored_chunks(session)
        context = self._format_context(context_docs)

        # convert session messages to LangChain format for history
        # excludes the current user_input since it's passed separately as {input}
        lc_history = self._build_history(session)

        base_args = {
            "active_problem_query": session.active_problem_query,
            "selected_topics": ", ".join(session.selected_topics),
            "context": context,
            "history": lc_history,
            "input": user_input
        }

        if session.ta_stage == 1:
            # first turn — ask the locating question
            print("\n[Socratic Engine] Executing Stage 1 (Locating Question)")
            reply = self._run(self._stage1_prompt, base_args)
            session.advance_stage()

        elif session.ta_stage == 2:
            # assess student's reply to stage 1 then branch
            assessment = self._assess_reply(session, user_input)
            print(f"\n[Socratic Engine] Flash assessed student reply as: {assessment}")
            print(f"[Socratic Engine] Executing Stage 2 ({assessment})")
            prompt = self._pick_stage2_prompt(assessment)
            reply = self._run(prompt, base_args)
            session.advance_stage()

        elif session.ta_stage == 3:
            # final push regardless of what student said
            print("\n[Socratic Engine] Executing Stage 3 (Final Push)")
            reply = self._run(self._stage3_prompt, base_args)
            session.advance_stage()

        else:
            # stage 4 — overflow direct answer, then reset
            print("\n[Socratic Engine] Executing Stage 4 (Direct Overflow)")
            reply = self._run(self._stage4_prompt, base_args)
            session.reset_socratic_state()

        return reply

    def respond_out_of_scope(self, user_input: str, selected_topics: List[str], lecture_number: int) -> str:
        """
        Handles OUT_OF_SCOPE queries.
        No retrieval, no session state, no stages — just a clean redirect.
        Called directly by QueryRouter when Flash classifies a query as out of scope.
        """
        #chain = self._out_of_scope_prompt | self.llm | self.parser
        #return chain.invoke({"input": user_input})
        """
        Handles OUT_OF_SCOPE queries with two distinct behaviors:

        1. If the topic appears in a future lecture the student hasn't reached yet —
           acknowledge it's coming up in the course and encourage them to keep it in mind.

        2. If the topic has no connection to the course at all —
           clean two sentence redirect back to what CourseLens covers.

        No retrieval, no session state, no stages in either case.
        """
        future_lecture = self._check_future_lectures(selected_topics, lecture_number)

        if future_lecture:
            # topic exists in course but student hasn't reached it yet
            chain = self._future_lecture_prompt | self.llm | self.parser
            return chain.invoke({
                "input": user_input,
                "future_lecture": future_lecture
            })

        # true out of scope — no connection to course at all
        chain = self._out_of_scope_prompt | self.llm | self.parser
        return chain.invoke({"input": user_input})


    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _check_future_lectures(self, selected_topics: List[str], lecture_number: int) -> Optional[str]:
        """
        Checks if any of the selected topics appear in lectures beyond the
        student's current lecture_number.

        Returns a human-readable string like "Lecture 9 (Pointers)" if found,
        or None if the topic has no connection to the course at all.
        """
        if lecture_number is None:
            return None
        
        loader = SyllabusLoader()

        # check each lecture beyond the student's current position
        for future_lec in range(lecture_number + 1, 15):
            future_topics = loader.get_topics(future_lec)
            for topic in selected_topics:
                if topic in future_topics:
                    return f"Lecture {future_lec}"

        return None

 
    def _build_history(self, session: ChatSession) -> list:
        """
        Converts session messages to LangChain HumanMessage and AIMessage objects.
        Only includes messages from the start of the current Socratic loop —
        not the full session history — to keep context focused on the active problem.
        """
        lc_msgs = []
        in_loop = False

        for msg in session.messages:
            # start capturing from the message that triggered the Socratic loop
            if msg.role == "user" and msg.content == session.active_problem_query:
                in_loop = True
            if in_loop:
                if msg.role == "user":
                    lc_msgs.append(HumanMessage(content=msg.content))
                else:
                    lc_msgs.append(AIMessage(content=msg.content))

        return lc_msgs

    def _assess_reply(self, session: ChatSession, student_reply: str) -> str:
        """
        Flash call to assess student's reply to stage 1.
        Returns one of: LOCATED, WRONG_DIRECTION, NO_ATTEMPT
        """
        chain = self._assessor_prompt | self.flash_llm | self.parser
        result = chain.invoke({
            "active_problem_query": session.active_problem_query,
            "selected_topics": ", ".join(session.selected_topics),
            "student_reply": student_reply
        }).strip().upper()

        # default to NO_ATTEMPT if Flash returns something unexpected
        return result if result in [
            ReplyAssessment.LOCATED,
            ReplyAssessment.WRONG_DIRECTION,
            ReplyAssessment.NO_ATTEMPT
        ] else ReplyAssessment.NO_ATTEMPT

    def _pick_stage2_prompt(self, assessment: str) -> ChatPromptTemplate:
        """Returns the correct stage 2 prompt based on reply assessment."""
        if assessment == ReplyAssessment.LOCATED:
            return self._stage2_located_prompt
        elif assessment == ReplyAssessment.WRONG_DIRECTION:
            return self._stage2_wrong_prompt
        else:
            return self._stage2_no_attempt_prompt

    def _run(self, prompt: ChatPromptTemplate, args: dict) -> str:
        """Runs a prompt through the generation LLM and returns plain string."""
        chain = prompt | self.llm | self.parser
        return chain.invoke(args)

    def _format_context(self, docs: List[Document]) -> str:
        """
        Formats anchored docs into a context string for the prompt.
        Mirrors _format_docs in ChatPipeline for consistency.
        """
        if not docs:
            return "No course material available."

        formatted = []
        for doc in docs:
            source = doc.metadata.get("source_file", "Unknown")
            title = doc.metadata.get("title", "")
            slide = doc.metadata.get("slide_number", "")
            chunk_type = doc.metadata.get("chunk_type", "")

            if chunk_type == "parent":
                citation = f"Source: {source}, Title: {title}"
            else:
                citation = f"Source: {source}, Title: {title}, Slide: {slide}"

            formatted.append(f"{citation}\n{doc.page_content}")

        return "\n\n".join(formatted)