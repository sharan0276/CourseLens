from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from domain.chat_session import ChatSession
from services.rag.retrieval_service import RetrievalService
from typing import List

class SummarizationEngine:
    """
    Service responsible for summarizing full lectures or weeks.
    Supports both single-lecture detail and cumulative course-wide synthesis.
    """
    
    def __init__(self, llm, retrieval_service: RetrievalService):
        self.llm = llm
        self.retrieval_service = retrieval_service
        
        self._summarize_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert teaching assistant outlining course material.\n"
             "The student has asked for a summary of a specific lecture or week.\n"
             "Below is the complete ordered transcript and slide contents of the lecture.\n\n"
             "Your goal is to provide a comprehensive, well-structured summary of these materials.\n"
             "Rules:\n"
             "1. Start with a high-level overview of what the lecture covered.\n"
             "2. Break down the key concepts into bullet points, using bolding for important terms.\n"
             "3. If there are code examples or technical definitions, briefly summarize the core takeaway.\n"
             "4. Do not invent information not present in the provided text.\n"
             "5. Keep the formatting clean and readable.\n\n"
             "Lecture Context:\n{context}"),
            ("human", "{user_input}")
        ])

        self._recap_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert teaching assistant providing a HIGH-SIGNAL RECAP of a single lecture.\n"
             "Identify only the most critical 3-4 core pillars or 'Aha!' moments from this lecture.\n"
             "Be extremely concise. Use one sentence per pillar.\n\n"
             "Lecture Context:\n{context}"),
            ("human", "Recap this lecture concisely.")
        ])

        self._synthesize_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert teaching assistant providing a 'Knowledge Map' of the course so far.\n"
             "The student wants to know what they've learned up to a certain point.\n"
             "Below is a collection of high-level recaps from multiple lectures.\n\n"
             "Your goal is to provide a concise summary that 'connects the dots' between weeks.\n"
             "Rules:\n"
             "1. Focus on progression: How did earlier weeks lead into later ones?\n"
             "2. Use a 'Progress Timeline' format (e.g. 'Starting with...', 'Building on that...', 'Most recently...').\n"
             "3. Be high-signal. Avoid slide-level detail. Provide a bird's eye view.\n\n"
             "Course Context (Lectures 1 to {target_lecture}):\n{context}"),
            ("human", "{user_input}")
        ])

    def summarize(self, session: ChatSession, lecture_number: int, user_input: str, is_until: bool = False) -> str:
        """
        Main entry point for summarization. 
        If is_until is True, performs a modular cross-lecture synthesis.
        Otherwise, provides a detailed summary of a single lecture.
        """
        if lecture_number is None:
            return "I need a specific lecture or week number to summarize. Could you clarify which one?"
            
        if is_until:
            return self._summarize_modular_range(lecture_number, user_input)
            
        # Single-lecture detailed summary
        docs = self.retrieval_service.fetch_lecture_for_summary(lecture_number)
        
        if not docs:
            return f"I couldn't find any material for lecture {lecture_number}."
            
        full_context = self._format_docs_for_context(docs)
        
        # Standard detailed summary chain
        chain = self._summarize_prompt | self.llm | StrOutputParser()
        return chain.invoke({"context": full_context, "user_input": user_input})

    def _summarize_modular_range(self, target_lecture: int, user_input: str) -> str:
        """
        Loops through lectures 1 → target_lecture, recapping each before synthesizing.
        This provides best token efficiency and pedagogical structure.
        """
        recaps = []
        print(f"\n[Summarizer] Building modular recap range (1 to {target_lecture})...")
        
        for lec_id in range(1, target_lecture + 1):
            docs = self.retrieval_service.fetch_lecture_for_summary(lec_id)
            if not docs:
                continue
                
            print(f"[Summarizer]   > Recapping Lecture {lec_id}...")
            context = self._format_docs_for_context(docs)
            recap_chain = self._recap_prompt | self.llm | StrOutputParser()
            recap = recap_chain.invoke({"context": context})
            recaps.append(f"LECTURE {lec_id} RECAP:\n{recap}")

        full_context = "\n\n".join(recaps)
        
        # Final synthesis Knowledge Map
        print(f"[Summarizer] Synthesizing final Knowledge Map...")
        synth_chain = self._synthesize_prompt | self.llm | StrOutputParser()
        return synth_chain.invoke({
            "context": full_context, 
            "target_lecture": target_lecture,
            "user_input": user_input
        })

    def _format_docs_for_context(self, docs: List) -> str:
        """Helper to format slide summaries into a coherent text block."""
        context_parts = []
        for doc in docs:
            raw_slide = doc.metadata.get("slide_number", "Unknown")
            if isinstance(raw_slide, (int, float)):
                slide_no = str(int(raw_slide))
            elif isinstance(raw_slide, str):
                slide_no = raw_slide[:-2] if raw_slide.endswith(".0") else raw_slide
            else:
                slide_no = str(raw_slide)
            title = doc.metadata.get("title", "")
            
            # Use metadata summary if available, fallback to full text
            summary = doc.metadata.get("chunk_summary")
            content = summary if summary else doc.page_content
            
            context_parts.append(f"--- Slide {slide_no}: {title} ---\n{content}")
        return "\n\n".join(context_parts)
