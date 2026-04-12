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
    BUG_RESOLVED = "BUG_RESOLVED" # student successfully fixed the specific bug being discussed, but other bugs remain
    CORRECT = "CORRECT"           # student has successfully provided the final intended answer or core logic
    BYPASS = "BYPASS"             # student explicitly asked for the answer, to skip, or to stop the hints


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
             "NO_ATTEMPT — student said they don't know, gave no answer, is clearly lost, or asked for a hint/help WITHOUT explicitly asking to skip the pedagogical process\n"
             "BYPASS — student explicitly asked to skip to the answer, for the full explanation now, or to 'just tell me' (e.g., 'just tell me', 'skip to explanation', 'I want the answer', 'give me the fix')\n"
             "BUG_RESOLVED — student successfully fixed or correctly answered the specific issue being discussed, but other bugs might remain\n"
             "CORRECT — student has successfully provided the final intended answer or solved the core logic problem described in the original question ({active_problem_query})\n\n"
             "IMPORTANT: Use the conversation history to understand what the tutor just asked or hinted. If the student correctly provided the information the tutor was looking for, mark it as LOCATED or BUG_RESOLVED accordingly.\n"
             "BE GENEROUS AND CONTEXT-AWARE: If the student identifies the core idea or describes a highly related technical process (e.g., 'running code' for 'testing', 'loading/executing' for 'observing behavior'), mark it as BUG_RESOLVED. Avoid pedantry: our goal is to validate their correct intuition even if they don't use the exact textbook term yet.\nIf the student is 80% correct but has one small misconception, you may still use WRONG_DIRECTION to trigger a correction, but ensure you FIRST validate their correct reasoning in your response.\n\n"
             "Reply with ONLY the label. No explanation."),
            MessagesPlaceholder("history"),
            ("human", "{student_reply}")
        ])

        # ── Stage 1 Prompt — Locating Question ───────────────────────────────
        # never gives the answer — purely probes student self-location
        self._stage1_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
             "A student has asked a question that needs guided understanding.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Your job at this stage is to ask ONE open-ended locating question.\n"
             "The question should probe what concept or topic the student thinks this relates to.\n\n"
             "STRICT RULES:\n"
             "1. Do NOT answer the question\n"
             "2. Do NOT give any hints toward the answer\n"
             "3. Do NOT explicitly list the course topics (like 'Program Organization') to the student. Make it a natural, human-like, open-ended question.\n"
             "4. Keep it extremely brief and conversational — one or two sentences maximum.\n"
             "5. Check the conversation history. If the history contains discussions about OTHER topics or previous questions, IGNORE them for your opening. ONLY if the history shows you are already mid-discussion about THIS SPECIFIC question ({active_problem_query}), you may use words like 'As we discussed' or 'We've talked about'. If this is the FIRST response to this specific doubt, you MUST start naturally and freshly without referencing the past.\n"
             "6. STRICT GROUNDING RULE: DO NOT synthesize, explain, or acknowledge the functionality of any syntax, operators, or logical constructs NOT explicitly present in the provided `{context}`. If the student's code contains an 'unknown' element (to the course), treat it as an error and redirect them to the 'known' materials in your question. EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "7. You may synthesize relatable analogies or examples (e.g. 'building blocks') to clarify the foundational concept, provided they do not contradict context. Do NOT introduce advanced C++ features or libraries not mentioned in context. Your goal is pedagogical clarity.\n"
             "8. CITATION RULE: You MUST mention the specific slide and file NATURALLY in your response (e.g., 'Take a look at chap02.pptx, Slide 26' or 'Refer to Slide 40 of chap03.pptx'). MANDATORY: Never use the bracketed format [filename, Slide N] at this stage.\n\n"
             "Context from course material:\n{context}"),

            ("human", "{input}")
        ])

        # ── Stage 2 Prompt — Lead ─────────────────────────────────────────────
        # branches based on reply assessment — three distinct behaviors
        self._stage2_located_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
             "The student correctly identified the relevant concept area.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Acknowledge what they got right, then provide ONE specific hint or leading "
             "observation that points them toward the answer without giving it away.\n\n"
             "STRICT RULES:\n"
             "1. Do NOT give the full answer\n"
             "2. Guide them exactly ONE step forward, building firmly on what they already understand.\n"
             "3. Teach sequentially: always address foundational concepts before dependent steps.\n"
             "4. Check the conversation history. ONLY if you find that you have already discussed a related concept *within this specific Socratic loop* for the current question ({active_problem_query}), you MUST start your response with 'As we already discussed...' to acknowledge it. If the history is about a completely different previous question, do NOT use this phrase.\n"
             "5. STRICT GROUNDING RULE: DO NOT synthesize, explain, or acknowledge the functionality of any syntax, operators, or logical constructs NOT explicitly present in the provided `{context}`. If the student's code contains an 'unknown' element (to the course), treat it as an error and redirect them to the 'known' materials. (e.g. if '==' is not in materials, do not explain it as 'comparison'; say it is unknown and point to the correct assignment operator in the slides). EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "6. You may synthesize relatable analogies or examples (e.g. 'building blocks') to clarify technical terms, even if those specific examples are not in the slides. Do NOT introduce advanced C++ features or libraries not mentioned in the text. Your goal is pedagogical clarity.\n"
             "7. CITATION RULE: You MUST mention the specific slide and file NATURALLY in your response (e.g., 'Take a look at chap02.pptx, Slide 26' or 'Refer to Slide 40 of chap03.pptx'). MANDATORY: Never use the bracketed format [filename, Slide N] at this stage.\n"
             "8. If the student has MULTIPLE misconceptions or code errors, silently identify all of them. YOU MUST STRICTLY PRIORITIZE conceptual logic over formatting typos. Guide them to fix ONE issue at a time. If they just resolved an issue but others remain, explicitly tell them there is another issue, and seamlessly guide them to locate the next one.\n"
             "9. ESCAPE HATCH: Once the student has successfully fixed ALL bugs AND completely resolved their conceptual misunderstandings, you MUST congratulate them and end your response with the exact magic word after your final sentence: '[COMPLETE]'. MANDATORY: Do NOT include any follow-up questions if you use this word.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        self._stage2_wrong_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
             "The student identified something but is heading in the wrong direction.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Briefly validate any correct reasoning, precisely correct their misconception, "
             "and provide exactly ONE hint to guide their next logical step.\n\n"
             "STRICT RULES:\n"
             "1. Do NOT give the full answer\n"
             "2. Correct the specific misconception, then explicitly ask ONE guiding question to lead them to the right path. You MUST end your response with a question mark.\n"
             "3. Check the conversation history. ONLY if you find that you have already discussed a related concept *within this specific Socratic loop* for the current question ({active_problem_query}), you MUST start your response with 'As we already discussed...' to acknowledge it. If the history is about a completely different previous question, do NOT use this phrase.\n"
             "4. Do not overwhelm — one correction + one hint only.\n"
             "5. STRICT GROUNDING RULE: DO NOT synthesize, explain, or acknowledge the functionality of any syntax, operators, or logical constructs NOT explicitly present in the provided `{context}`. If the student's code contains an 'unknown' element (to the course), treat it as an error and redirect them to the 'known' materials. (e.g. if '==' is not in materials, do not explain it as 'comparison'; say it is unknown and point to the correct assignment operator in the slides). EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "6. You may synthesize relatable analogies or examples (e.g. 'building blocks') to clarify technical terms, even if those specific examples are not in the slides. Do NOT introduce advanced C++ features or libraries not mentioned in the text. Your goal is pedagogical clarity.\n"
             "7. CITATION RULE: You MUST mention the specific slide and file NATURALLY in your response (e.g., 'Take a look at chap02.pptx, Slide 26' or 'Refer to Slide 40 of chap03.pptx'). MANDATORY: Never use the bracketed format [filename, Slide N] at this stage.\n"
             "8. If the student has MULTIPLE misconceptions or code errors, silently identify all of them. YOU MUST STRICTLY PRIORITIZE conceptual logic over formatting typos. Guide them to fix ONE issue at a time. If they just resolved an issue but others remain, explicitly tell them there is another issue, and seamlessly guide them to locate the next one.\n"
             "9. ESCAPE HATCH: Once the student has successfully fixed ALL bugs AND completely resolved their conceptual misunderstandings, you MUST congratulate them and end your response with the exact magic word after your final sentence: '[COMPLETE]'. MANDATORY: Do NOT include any follow-up questions if you use this word.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        self._stage2_no_attempt_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
             "The student is lost and could not locate the relevant concept.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Explain the foundational concept first using the course material, "
             "then bridge back to the student's original question.\n\n"
             "STRICT RULES:\n"
             "1. Keep the explanation brief — one short paragraph\n"
             "2. End by explicitly asking ONE guiding question to prompt the student's next step. You MUST end your response with a question mark.\n"
             "3. Check the conversation history. ONLY if you find that you have already discussed a related concept *within this specific Socratic loop* for the current question ({active_problem_query}), you MUST start your response with 'As we already discussed...' to acknowledge it. If the history is about a completely different previous question, do NOT use this phrase.\n"
             "4. Do NOT give the full answer to the original question yet\n"
             "5. STRICT GROUNDING RULE: You must prioritize the provided `{context}`. However, you MAY synthesize foundational computing concepts (like binary arithmetic, bitwise logic, or memory addresses) to explain the 'HOW' or 'WHY' if the student is stuck. Do NOT introduce advanced C++ features or outside libraries not in context. Your goal is pedagogical clarity. EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "6. You may synthesize relatable analogies or examples (e.g. 'building blocks') to clarify technical terms, even if those specific examples are not in the slides.\n"
             "7. CITATION RULE: You MUST mention the specific slide and file NATURALLY in your response (e.g., 'Check chap03.pptx, Slide 40' or 'Refer to chap02.pptx, Slide 26'). MANDATORY: Never use the bracketed format [filename, Slide N] at this stage.\n"
             "8. If the student has MULTIPLE misconceptions or code errors, silently identify all of them. YOU MUST STRICTLY PRIORITIZE conceptual logic over formatting typos. Guide them to fix ONE issue at a time. If they just resolved an issue but others remain, explicitly tell them there is another issue, and seamlessly guide them to locate the next one.\n"
             "9. ESCAPE HATCH: Once the student has successfully fixed ALL bugs AND completely resolved their conceptual misunderstandings, you MUST congratulate them and end your response with the exact magic word after your final sentence: '[COMPLETE]'. MANDATORY: Do NOT include any follow-up questions if you use this word.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        # ── Stage 3 Prompt — Final Push ───────────────────────────────────────
        # student should be able to reach the answer from here
        self._stage3_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
             "The student is ready for the final push toward the answer.\n\n"
             "Original question: {active_problem_query}\n"
             "Relevant course topics: {selected_topics}\n\n"
             "Give the student actionable, specific, directional guidance that "
             "lets them reach the answer themselves. They should not need another hint after this.\n\n"
             "STRICT RULES:\n"
             "1. Still do NOT give the full answer directly\n"
             "2. Be specific and concrete — vague nudges are not helpful at this stage\n"
             "3. STRICT GROUNDING RULE: You must prioritize the provided `{context}`. However, you MAY synthesize foundational computing concepts (like binary arithmetic, bitwise logic, or memory addresses) to explain the 'HOW' or 'WHY' if the student is stuck. Do NOT introduce advanced C++ features or outside libraries not in context. EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "4. CITATION RULE: You MUST mention the specific slide and file NATURALLY in your response (e.g., 'Take a look at chap02.pptx, Slide 26' or 'Check Slide 40 of chap03.pptx'). MANDATORY: Never use the bracketed format [filename, Slide N] at this stage.\n"
             "5. Use bullet points for technical lists or multi-step explanations to improve readability.\n"
             "6. ESCAPE HATCH: Once the student has successfully fixed ALL bugs AND completely resolved their conceptual misunderstandings, you MUST congratulate them and end your response with the exact magic word after your final sentence: '[COMPLETE]'. MANDATORY: Do NOT include any follow-up questions if you use this word.\n\n"
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])

        # ── Stage 4 Prompt — Debrief + Direct Answer ──────────────────────────
        # overflow only — structured debrief, NOT another question
        self._stage4_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor.\n"
             "The student has reached the end of the guided session without fully arriving at the answer.\n"
             "Your job now is to give a warm, structured DEBRIEF — not another question, not a hint. A full answer with context.\n\n"
             "Original question: {active_problem_query}\n\n"
             "Structure your response in this exact order:\n"
             "1. JOURNEY RECAP (1-2 sentences): Briefly acknowledge what we explored together.\n"
             "2. THE REASONING: Explain THE CORE CONCEPTS DISCUSSED SO FAR and WHY the hints pointed there. You MAY synthesize foundational computing concepts (like binary arithmetic or memory layout) to bridge the gap between the slide content and a complete mental model for the student.\n"
             "3. PARTIAL ANSWER & CODE STATUS: Provide the direct answer or code fix **ONLY** for the specific sub-tasks or bugs that were discussed during this Socratic session. **MANDATORY**: You MUST explicitly tell the student that the code is NOT yet fully fixed and there are still other errors to find. Do NOT provide the fix for anything not discussed yet—this is a partial reveal only.\n"
             "4. ENCOURAGEMENT: Explicitly congratulate the student on the progress they've made with these specific points. Encourage them to use the same logic to figure out the next error on their own in a new session.\n\n"
             "STRICT RULES:\n"
             "1. MANDATORY — ABSOLUTELY DO NOT ask any questions whatsoever. Not rhetorical, not clarifying, not follow-up. Zero questions. Since you are performing a PARTIAL REVEAL (Section 3), you must only fix the bugs/concepts discussed. For all other unresolved issues, simply state that the student should try to solve them in a new session.\n"
             "2. STRICT GROUNDING RULE: You must prioritize the provided `{context}`. However, you MAY synthesize foundational computing concepts (like binary arithmetic or bitwise logic) to provide a clear and complete technical explanation in section 2 (Reasoning). Do NOT introduce advanced C++ features or outside libraries not in context. EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "3. Be warm and encouraging, not dismissive.\n"
             "4. Keep each section concise. Total response should not exceed 15 sentences.\n"
             "5. Use the exact format [filename, Slide N] after factual claims for citations. Do NOT use [1] or [2] yourself.\n"
             "6. If a retrieved document contains 'Attached Images', include it using: `![Description](CourseLens_data/images/<filename>)`.\n"
             "7. COMPREHENSIVENESS RULE: For all concepts or sub-tasks discussed, ensure the explanations are comprehensive. If there are multiple parts to an answer, list all of them and explain the 'why' behind each.\n\n" # FIX: Ensured comprehensive listing and explanation in debrief
             "Context from course material:\n{context}"),

            MessagesPlaceholder("history"),
            ("human", "{input}")
        ])


        # ── Out of Scope Prompt ───────────────────────────────────────────────
        # no retrieval, no stages — two sentence redirect back to course content
        self._out_of_scope_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
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
             "You are the CourseLens Socratic Tutor, an expert on the entire breadth of this course (from General Computing, Binary, and Architecture basics to C++ Programming).\n"
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

        # ── Success Summary Prompt ───────────────────────────────────────────
        self._success_summary_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a C++ teaching assistant.\n"
             "The student has successfully resolved the bugs in their code through a guided Socratic process, or they submitted completely correct code.\n"
             "Your job is to provide a brief, encouraging summary of what they just accomplished.\n\n"
             "STRICT RULES:\n"
             "1. Congratulate the student on their success.\n"
             "2. VALIDATE EFFORT: If the student successfully navigated the Socratic hints (check history), explicitly praise them for 'taking a chance' on the hints and using them to reach the breakthrough. Tell them this 'courage to apply the theory' is what masters C++.\n"
             "3. Briefly list the specific logic or syntax errors they corrected during this conversation. If their original code had no bugs to begin with, just congratulate them on a perfect implementation.\n"
             "4. STRICT GROUNDING RULE: You must prioritize the provided `{context}`. However, you MAY synthesize foundational computing concepts (like binary arithmetic or memory addresses) to complete the mental model for the student. Do NOT introduce outside C++ theory. EXCEPTION: If the student correctly brings up an advanced computing concept or analogy (e.g. Inheritance) not in the material, you MUST enthusiastically validate their connection first, and then seamlessly map their advanced understanding back to the current simplified course topic.\n"
             "5. Keep the summary encouraging and concise (bullet points are great).\n"
             "6. Do NOT ask any further Socratic questions.\n\n"
             "FORMATTING & CITATION RULES:\n"
             "1. Use bullet points for technical lists or multi-step explanations to improve readability.\n"
             "2. Use the exact format [filename, Slide N] directly in the text after factual claims (e.g., 'C++ uses cout for output [chap01.pptx, Slide 7]'). Do NOT use [1] or [2] yourself; the system will automatically convert your bracketed citations into sequential numbers for the user.\n\nCRITICAL: If a retrieved document contains 'Attached Images', and the image is relevant to your answer, you MUST include it using markdown: `![Description](CourseLens_data/images/<filename>)`. Ensure diagrams like the Control Unit are shown when explaining them."
             "Context from course material:\n{context}"),
            MessagesPlaceholder("history"),
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

        # DETERMINISTIC ESCAPE HATCH: If student explicitly wants to skip, jump immediately to Stage 4
        # Reinstating the original string-matching logic
        user_input_lower = user_input.lower()
        if "skip to explanation" in user_input_lower or "just give me the answer" in user_input_lower:
            print("[Socratic Engine] Deterministic Escape Hatch triggered. Jumping to Stage 4.")
            session.ta_stage = 4
            reply = self._run(self._stage4_prompt, base_args)
            reply = f"[📘 Stage 4 - Debrief & Full Answer]\n\n{reply}"
            session.reset_socratic_state()
            return reply

        if session.ta_stage == 1:
            # first turn — ask the locating question
            print("\n[Socratic Engine] Executing Stage 1 (Locating Question)")
            reply = self._run(self._stage1_prompt, base_args)
            reply += "\n\n*(Tip: say **\"just tell me\"** or **\"skip to explanation\"** at any point to get the direct answer.)*"
            reply = f"[💡 Stage 1 - Locating Concept]\n\n{reply}"
            session.advance_stage()
            return reply

        # Process Assessment for active stages (2 and 3). 
        # We skip assessment for Stage 4 because it is a direct debrief.
        assessment = None
        if session.ta_stage < 4:
            assessment = self._assess_reply(session, user_input)
            print(f"\n[Socratic Engine] Flash assessed student reply as: {assessment}")

        # Use a loop to support "Instant Transitions" (e.g. Stage 1 Bail -> Stage 2 Hint or Bypass -> Stage 4)
        while True:
            # INSTANT ESCAPE HATCH: If student explicitly wants to skip, jump immediately to Stage 4
            if assessment == ReplyAssessment.BYPASS:
                print("[Socratic Engine] Student invoked Escape Hatch (BYPASS). Jumping to Stage 4.")
                session.ta_stage = 4
                # fall through to Stage 4 logic below
            if session.ta_stage == 4:
                # Stage 4 fires UNCONDITIONALLY — no assessment, no more questions
                print("\n[Socratic Engine] Executing Stage 4 (Debrief + Direct Answer)")
                reply = self._run(self._stage4_prompt, base_args)
                reply = f"[\U0001f4d8 Stage 4 - Debrief & Full Answer]\n\n{reply}"
                session.reset_socratic_state()
                return reply

            elif session.ta_stage == 2:
                print(f"[Socratic Engine] Executing Stage 2 ({assessment})")

                if assessment == ReplyAssessment.NO_ATTEMPT:
                    print("[Socratic Engine] Student surrendered/stuck at Stage 2. Providing Stage 2 explanation and advancing.")
                    reply = self._run(self._stage2_no_attempt_prompt, base_args)
                    reply = f"[🧭 Stage 2 - Leading (Assessment: NO_ATTEMPT)]\n\n{reply}"
                    session.advance_stage()
                    return reply
                
                # Effort-based Looping (Wrong/Located/Bug Resolved/Correct)
                if assessment in [ReplyAssessment.BUG_RESOLVED, ReplyAssessment.CORRECT]:
                    print(f"[Socratic Engine] Success identified ({assessment})! Checking for completion...")
                    session.ta_stage = 2
                    prompt = self._stage2_located_prompt
                else:
                    prompt = self._pick_stage2_prompt(assessment)
                
                reply = self._run(prompt, base_args)
                if "[COMPLETE]" in reply:
                    print("[Socratic Engine] All bugs fixed! Generating Success Summary.")
                    reply = self._run(self._success_summary_prompt, base_args)
                    session.reset_socratic_state()
                    reply = f"[\U0001f389 Socratic Loop Complete! Validation Summary]\n\n{reply}"
                    return reply
                else:
                    header = "\u2714\ufe0f SUCCESS DETECTED! Refreshing Loop for Next Issue" if assessment in [ReplyAssessment.BUG_RESOLVED, ReplyAssessment.CORRECT] else f"\U0001f9ed Stage 2 - Leading (Assessment: {assessment})"
                    if f"[{header}]" not in reply:
                        reply = f"[{header}]\n\n{reply}"
                    return reply

            elif session.ta_stage == 3:
                print("\n[Socratic Engine] Executing Stage 3 (Final Push)")
                
                # Check for Surrender first for progression to 4
                if assessment == ReplyAssessment.NO_ATTEMPT:
                    # To prevent premature ejection to Stage 4, check if they've actually seen the Stage 3 hint yet.
                    last_bot_msg = ""
                    for msg in reversed(session.messages):
                        if msg.role == "assistant":
                            last_bot_msg = msg.content
                            break
                            
                    if "[🎯 Stage 3 - Final Push]" in last_bot_msg:
                        # They surrendered AFTER reading the Stage 3 hint. Time for debrief!
                        print("[Socratic Engine] Student surrendered at Final Push. Advancing to Stage 4 Debrief.")
                        session.advance_stage()
                        # We must recurse or immediately execute Stage 4 to show the debrief
                        return self.respond(session, user_input)
                    else:
                        # They surrendered to the Stage 2 hint. Give them the Stage 3 hint, but stay in Stage 3!
                        print("[Socratic Engine] Providing Stage 3 hint and waiting for answer.")
                        reply = self._run(self._stage3_prompt, base_args)
                        reply = f"[🎯 Stage 3 - Final Push]\n\n{reply}"
                        return reply

                # Handle Potential Success / Multi-Bug Persistence
                if assessment in [ReplyAssessment.CORRECT, ReplyAssessment.BUG_RESOLVED]:
                    print(f"[Socratic Engine] Potential success ({assessment})! Checking for remaining bugs...")
                    prompt = self._stage2_located_prompt
                    reply = self._run(prompt, base_args)

                    if "[COMPLETE]" in reply:
                        print("[Socratic Engine] All bugs fixed! Generating Success Reward.")
                        reply = self._run(self._success_summary_prompt, base_args)
                        session.reset_socratic_state()
                        reply = f"[\U0001f389 Socratic Loop Complete! Success Reward]\n\n{reply}"
                        return reply
                    else:
                        print("[Socratic Engine] More bugs detected! Resetting to Stage 2 for the next one.")
                        session.ta_stage = 2
                        header = "\u2714\ufe0f BUG RESOLVED! Refreshing Loop for Next Bug"
                        if f"[{header}]" not in reply:
                            reply = f"[{header}]\n\n{reply}"
                        return reply
                
                # Effort-based Looping (LOCATED -> Revert to 2, WRONG_DIRECTION -> Stay in 3)
                elif assessment == ReplyAssessment.LOCATED:
                    print("[Socratic Engine] Student located the concept at Stage 3! Tightening reins, reverting to Stage 2.")
                    session.ta_stage = 2
                    prompt = self._stage2_located_prompt
                    reply = self._run(prompt, base_args)
                    reply = f"[\U0001f9ed Concept Located! Moving back to Leading Mode]\n\n{reply}"
                    return reply

                else:
                    # WRONG_DIRECTION stays in Stage 3 for another retry
                    reply = self._run(self._stage3_prompt, base_args)
                    if "[COMPLETE]" in reply:
                        print("[Socratic Engine] LLM detected NO BUGS! Generating Success Summary.")
                        reply = self._run(self._success_summary_prompt, base_args)
                        session.reset_socratic_state()
                        reply = f"[\U0001f389 Socratic Loop Complete! Validation Summary]\n\n{reply}"
                        return reply
                    else:
                        reply = f"[\U0001f3af Stage 3 - Final Push]\n\n{reply}"
                        return reply

        return reply

    def respond_out_of_scope(self, user_input: str, selected_topics: List[str], lecture_number: int) -> str:
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
        lc_history = self._build_history(session)
        result = chain.invoke({
            "active_problem_query": session.active_problem_query,
            "selected_topics": ", ".join(session.selected_topics),
            "history": lc_history,
            "student_reply": student_reply
        }).strip().upper()

        # default to NO_ATTEMPT if Flash returns something unexpected
        return result if result in [
            ReplyAssessment.LOCATED,
            ReplyAssessment.WRONG_DIRECTION,
            ReplyAssessment.NO_ATTEMPT,
            ReplyAssessment.BUG_RESOLVED,
            ReplyAssessment.CORRECT
        ] else ReplyAssessment.NO_ATTEMPT

    def _pick_stage2_prompt(self, assessment: str) -> ChatPromptTemplate:
        """Returns the correct stage 2 prompt based on reply assessment."""
        if assessment in [ReplyAssessment.LOCATED, ReplyAssessment.BUG_RESOLVED, ReplyAssessment.CORRECT]:
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
        Separates course material and web references into distinct sections.
        """
        if not docs:
            return "No course material available."

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

            source = doc.metadata.get("source_file", "Unknown")
            title = doc.metadata.get("title", "")
            slide = doc.metadata.get("slide_number", "")
            chunk_type = doc.metadata.get("chunk_type", "")
            image_filenames = doc.metadata.get("image_filenames", "")

            if chunk_type == "parent":
                citation = f"Source: {source}, Title: {title}"
            else:
                citation = f"Source: {source}, Title: {title}, Slide: {slide}"

            if image_filenames:
                image_filenames = image_filenames.replace(".emf", ".png")
                citation += f", Attached Images: {image_filenames}"

            course_docs.append(f"{citation}\n{doc.page_content}")

        sections = []
        if course_docs:
            sections.append("=== COURSE MATERIAL ===\n" + "\n\n".join(course_docs))
        if web_docs:
            sections.append("=== WEB REFERENCES (You MUST cite these using [SiteName: Title] format) ===\n" + "\n\n".join(web_docs))

        return "\n\n".join(sections)