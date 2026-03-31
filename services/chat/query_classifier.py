from typing import List, Optional
from dataclasses import dataclass
from enum import Enum
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from config.syllabus_loader import SyllabusLoader


class QueryType(Enum):
    DIRECT = "DIRECT"
    SOCRATIC = "SOCRATIC"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SUMMARIZE_LECTURE = "SUMMARIZE_LECTURE"


@dataclass
class ClassificationResult:
    query_type: QueryType
    selected_topics: List[str]
    target_lecture: Optional[int] = None


class QueryClassifier:
    """
    Single Flash call that classifies a student query and selects
    relevant topics from the syllabus in one shot.

    Returns a ClassificationResult with:
      - query_type: DIRECT, SOCRATIC, or OUT_OF_SCOPE
      - selected_topics: 2-3 verified topics from the syllabus (empty for OUT_OF_SCOPE)
    """

    def __init__(self, llm):
        self.llm = llm
        self.parser = StrOutputParser()

        self._prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a query classifier for a C++ university course assistant.\n\n"
             "Given a student query and the available course topics, do two things:\n\n"
             "   DIRECT      — factual question with a clear answer in the material\n"
             "                 e.g. 'What is a pointer?', 'What does const do?'\n"
             "                 ALSO use DIRECT if the student explicitly asks to validate if their code is correct, or if there are any remaining bugs.\n"
             "   SOCRATIC    — requires guided understanding, not just a fact\n"
             "                 includes conceptual confusion, debugging help, and background adjacent questions\n"
             "                 when in doubt, use SOCRATIC\n"
             "   SUMMARIZE_LECTURE — requests to summarize an entire lecture or a specific week's material\n"
             "                 e.g. 'Summarize lecture 3', 'What did we learn in week 2?'\n"
             "   OUT_OF_SCOPE — query has no meaningful connection to C++ programming fundamentals AND does not match any of the provided course topics.\n"
             "                 This includes: general knowledge trivia (politics, history, sports),\n"
             "                 questions about specific people or names unrelated to computing (e.g. 'who is Anirudh?', 'who is Einstein?'),\n"
             "                 calculations unrelated to programming logic, and queries about the AI assistant's own identity.\n"
             "                 IMPORTANT: If the query is completely unrelated to C++, it MUST be OUT_OF_SCOPE.\n\n"
             "2. Select 2-3 most relevant topics from the provided course topic list that relate to this query.\n"
             "   Only pick from the list — never invent topics.\n"
             "   For OUT_OF_SCOPE and CONVERSATIONAL queries, return no topics.\n\n"
             "Reply in exactly this format, nothing else:\n"
             "LABEL: <DIRECT|SOCRATIC|SUMMARIZE_LECTURE|OUT_OF_SCOPE>\n"
             "TOPICS: <topic1|topic2|topic3>\n"
             "TARGET_LECTURE: <lecture_number if specified, otherwise None>\n\n"
             "Available course topics:\n{topics}"),
            ("human", "{query}")
        ])

    # Prefixes that are always factual — skip LLM classification and force DIRECT
    _DIRECT_PREFIXES = (
        "what is ", "what are ", "what does ", "what do ",
        "what was ", "what were ", "define ", "list ", "list the",
        "how many ", "when did ",
    )

    # Prefixes that signal guided understanding — skip LLM and force SOCRATIC
    _SOCRATIC_PREFIXES = (
        "help me understand", "explain how", "i'm confused about",
        "i am confused about", "walk me through", "can you walk me through",
        "i don't understand", "i do not understand",
        "why does ", "why is ", "why do ", "why are ",
        "why did ", "why was ",
        "help me debug", "help me fix", "fix my", "debug my", "find the bug",
    )


    # Short greetings/pleasantries that are genuinely conversational
    _TRUE_CONVERSATIONAL = (
        "hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye",
        "ok", "okay", "yes", "no", "sure", "great", "cool",
        "what did i", "can you repeat", "what was my", "what have we",
    )

    def classify(self, query: str, lecture_number: int) -> ClassificationResult:
        """
        Single Flash call — returns classification label and verified selected topics.
        Defaults to SOCRATIC for any ambiguous or malformed response.
        """
        if lecture_number is None:
            lecture_number = 14  # assume entire course is available

        loader = SyllabusLoader()
        all_topics = loader.get_all_topics_up_to(lecture_number)

        # provide the LLM with all topics covered up to this point
        # so it doesn't wrongly flag older concepts as out-of-scope
        selection_pool = all_topics

        # ── Deterministic pre-check: factual question starters → always DIRECT ──
        q_lower = query.strip().lower()
        if any(q_lower.startswith(prefix) for prefix in self._DIRECT_PREFIXES):
            # Still call LLM just to get verified topics; override label to DIRECT
            topics_str = "\n".join(f"- {t}" for t in selection_pool)
            chain = self._prompt | self.llm | self.parser
            raw = chain.invoke({"query": query, "topics": topics_str}).strip()
            result = self._parse(raw, selection_pool)
            result = ClassificationResult(
                query_type=QueryType.DIRECT,
                selected_topics=result.selected_topics,
            )
            print(f"\n[Classifier] Pre-check forced DIRECT (factual prefix detected)")
            if result.selected_topics:
                print(f"[Classifier] Selected syllabus topics: {', '.join(result.selected_topics)}")
            return result

        topics_str = "\n".join(f"- {t}" for t in selection_pool)
        chain = self._prompt | self.llm | self.parser
        raw = chain.invoke({"query": query, "topics": topics_str}).strip()

        result = self._parse(raw, selection_pool)

        # ── Deterministic guard: ambiguous CONVERSATIONAL → OUT_OF_SCOPE ──────
        # Keep CONVERSATIONAL if:
        #   (a) it starts with a known greeting/meta-phrase, OR
        #   (b) the LLM found course-related topics (genuine course continuation)
        # Only downgrade to OUT_OF_SCOPE if NO course topics AND NOT a greeting.
        if result.query_type == QueryType.CONVERSATIONAL:
            is_greeting = any(q_lower.startswith(g) for g in self._TRUE_CONVERSATIONAL)
            has_course_topics = bool(result.selected_topics)
            if not is_greeting and not has_course_topics:
                print("\n[Classifier] CONVERSATIONAL downgraded to OUT_OF_SCOPE (no topics, not a greeting)")
                result = ClassificationResult(
                    query_type=QueryType.OUT_OF_SCOPE,
                    selected_topics=[],
                )


        print(f"\n[Classifier] Classified query as: {result.query_type.value}")
        if result.selected_topics:
            print(f"[Classifier] Selected syllabus topics: {', '.join(result.selected_topics)}")

        return result

    def _parse(self, raw: str, valid_topics: List[str]) -> ClassificationResult:
        """
        Parses Flash output into a ClassificationResult.
        Defaults to SOCRATIC and empty topics on any parse failure.
        """
        label = QueryType.SOCRATIC
        topics = []
        target_lecture = None

        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("LABEL:"):
                value = line.replace("LABEL:", "").strip().upper()
                label = {
                    "DIRECT": QueryType.DIRECT,
                    "SOCRATIC": QueryType.SOCRATIC,
                    "OUT_OF_SCOPE": QueryType.OUT_OF_SCOPE,
                    "SUMMARIZE_LECTURE": QueryType.SUMMARIZE_LECTURE,
                }.get(value, QueryType.SOCRATIC)

            elif line.startswith("TOPICS:"):
                raw_topics = line.replace("TOPICS:", "").strip()
                parsed = [t.strip() for t in raw_topics.split("|") if t.strip()]
                # verify each topic exists in the syllabus pool
                topics = [t for t in parsed if t in valid_topics]
            
            elif line.startswith("TARGET_LECTURE:"):
                val = line.replace("TARGET_LECTURE:", "").strip()
                if val and val.lower() != "none" and val.isdigit():
                    target_lecture = int(val)

        # if OUT_OF_SCOPE, clear topics regardless
        if label == QueryType.OUT_OF_SCOPE:
            topics = []

        # if nothing verified and not out of scope, it's likely a conversational tangent or out of scope
        if not topics and label != QueryType.OUT_OF_SCOPE:
            if label == QueryType.SOCRATIC or label == QueryType.DIRECT:
                # If we were sure it was course-related but couldn't find a topic, 
                # downgrade to OUT_OF_SCOPE to prevent hallucinating a syllabus match
                label = QueryType.OUT_OF_SCOPE
            topics = []

        return ClassificationResult(query_type=label, selected_topics=topics, target_lecture=target_lecture)