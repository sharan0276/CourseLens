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
             "   SOCRATIC    — requires guided understanding, not just a fact\n"
             "                 includes conceptual confusion, debugging help, and background adjacent questions\n"
             "                 when in doubt, use SOCRATIC\n"
             "   SUMMARIZE_LECTURE — requests to summarize an entire lecture or a specific week's material\n"
             "                 e.g. 'Summarize lecture 3', 'What did we learn in week 2?'\n"
             "   OUT_OF_SCOPE — query has no meaningful connection to C++ programming fundamentals AND does not match any of the provided course topics.\n"
             "                 Topics completely unrelated to C++ or the provided syllabus should be OUT_OF_SCOPE.\n"
             "                 IMPORTANT: If the query mentions keywords or concepts present in the provided course topics, it is NEVER OUT_OF_SCOPE.\n\n"
             "2. Select 2-3 most relevant topics from the provided course topic list that relate to this query.\n"
             "   Only pick from the list — never invent topics.\n"
             "   For OUT_OF_SCOPE queries, return no topics.\n\n"
             "Reply in exactly this format, nothing else:\n"
             "LABEL: <DIRECT|SOCRATIC|SUMMARIZE_LECTURE|OUT_OF_SCOPE>\n"
             "TOPICS: <topic1|topic2|topic3>\n"
             "TARGET_LECTURE: <lecture_number if specified, otherwise None>\n\n"
             "Available course topics:\n{topics}"),
            ("human", "{query}")
        ])

    def classify(self, query: str, lecture_number: int) -> ClassificationResult:
        """
        Single Flash call — returns classification label and verified selected topics.
        Defaults to SOCRATIC for any ambiguous or malformed response.
        """
        if lecture_number is None:
            lecture_number = 14  # assume entire course is available

        loader = SyllabusLoader()
        all_topics = loader.get_all_topics_up_to(lecture_number)
        current_topics = loader.get_topics(lecture_number)

        # provide the LLM with all topics covered up to this point
        # so it doesn't wrongly flag older concepts as out-of-scope
        selection_pool = all_topics
            
        topics_str = "\n".join(f"- {t}" for t in selection_pool)

        chain = self._prompt | self.llm | self.parser
        raw = chain.invoke({"query": query, "topics": topics_str}).strip()

        result = self._parse(raw, selection_pool)
        
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

        # if nothing verified and not out of scope, fall back to first 2 topics
        if not topics and label != QueryType.OUT_OF_SCOPE:
            topics = valid_topics[:2]

        return ClassificationResult(query_type=label, selected_topics=topics, target_lecture=target_lecture)