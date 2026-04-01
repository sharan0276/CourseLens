from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from domain.chat_session import ChatSession
from services.rag.retrieval_service import RetrievalService

class SummarizationEngine:
    """
    Service responsible for summarizing full lectures or weeks.
    It bypasses standard similarity RAG and fetches all chunks for the requested lecture/week.
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

    def summarize(self, session: ChatSession, lecture_number: int, user_input: str) -> str:
        """
        Fetches all chunks for the lecture, concatenates them, and runs the LLM summarization prompt.
        """
        if lecture_number is None:
            return "I need a specific lecture or week number to summarize. Could you clarify which one?"
            
        docs = self.retrieval_service.fetch_lecture_for_summary(lecture_number)
        
        if not docs:
            return f"I couldn't find any material for lecture {lecture_number}."
            
        # Concatenate all docs sequentially using the pre-computed ingestion summaries
        context_parts = []
        for doc in docs:
            slide_no = doc.metadata.get("slide_number", "Unknown")
            title = doc.metadata.get("title", "")
            
            # Use metadata summary if available, fallback to full text
            summary = doc.metadata.get("chunk_summary")
            content = summary if summary else doc.page_content
            
            context_parts.append(f"--- Slide {slide_no}: {title} ---\n{content}")
            
        full_context = "\n\n".join(context_parts)
        
        # We assume the LLM has a large context window (e.g. Gemini), so we stuff it.
        chain = self._summarize_prompt | self.llm | StrOutputParser()
        
        reply = chain.invoke({
            "context": full_context,
            "user_input": user_input
        })
        
        return reply
