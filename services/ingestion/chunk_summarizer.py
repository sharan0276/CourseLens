from typing import List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

class ChunkSummarizer:
    """
    Service responsible for summarizing individual chunks during the ingestion pipeline.
    This condenses the raw text so that runtime full-lecture summarizations are much faster
    and cheaper by pulling these pre-computed summaries instead of full text.
    """
    
    def __init__(self, llm):
        self.llm = llm
        
        self._summarize_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a helpful assistant structuring course material.\n"
             "Please provide a concise 1-2 sentence summary of the core concepts in the following text.\n"
             "Do not use overly verbose language. Just capture the key takeaway or definition.\n\n"
             "Text:\n{text}"),
            ("human", "Summarize this chunk.")
        ])
        
        self.chain = self._summarize_prompt | self.llm | StrOutputParser()

    def summarize_chunks(self, chunks: List[dict]) -> List[dict]:
        """
        Takes a list of chunk dictionaries, generates a summary for each using the LLM,
        and adds the summary to `chunk["metadata"]["chunk_summary"]`.
        """
        for chunk in chunks:
            text = chunk.get("text", "")
            title = chunk.get("metadata", {}).get("title", "")
            
            # Skip empty chunks or image-only chunks if they have no meaningful text besides title
            if not text.strip() or len(text.strip()) < 10:
                chunk["metadata"]["chunk_summary"] = title
                continue
                
            try:
                summary = self.chain.invoke({"text": text})
                chunk["metadata"]["chunk_summary"] = summary
            except Exception as e:
                print(f"Error summarizing chunk {chunk.get('id')}: {e}")
                # Fallback to a truncated version of the text if summarization fails
                chunk["metadata"]["chunk_summary"] = text[:200]
                
        return chunks
