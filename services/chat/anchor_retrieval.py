from typing import List
from langchain_core.documents import Document

from domain.chat_session import ChatSession
from services.rag.retrieval_service import RetrievalService


class AnchorRetrieval:
    """
    Handles the one-time retrieval step at the start of a Socratic loop.

    Core idea: retrieve once per selected topic, combine results, remove
    cross-topic duplicates, and store only chunk IDs in session.
    All subsequent stages fetch the same chunks by ID — no re-querying.

    RetrievalService already deduplicates within each topic's result set.
    This class only handles cross-topic duplicates using the same
    content-key approach RetrievalService uses internally.
    """

    def __init__(self, retrieval_service: RetrievalService, chunks_per_topic: int = 5):
        self.retrieval_service = retrieval_service
        self.chunks_per_topic = chunks_per_topic

    def anchor(self, session: ChatSession, topics: List[str], lecture_number: int) -> List[Document]:
        """
        Retrieves chunks for each selected topic, removes cross-topic duplicates,
        stores chunk IDs in session, and returns the full documents.

        Called once at stage 1 — never called again for the same Socratic loop.
        """
        all_docs = []

        for topic in topics:
            # each retrieve() call already deduplicates within its own result set
            topic_docs = self.retrieval_service.retrieve(
                query=topic,
                lecture_number=lecture_number,
                k=self.chunks_per_topic
            )
            all_docs.extend(topic_docs)

        # deduplicate across topics using same content-key approach as RetrievalService
        deduplicated = self._deduplicate_across_topics(all_docs)

        # store only chunk IDs in session — not full text — keeps session JSON lean
        session.anchored_chunk_ids = self._extract_ids(deduplicated)

        return deduplicated

    def fetch_anchored_chunks(self, session: ChatSession) -> List[Document]:
        """
        Fetches full chunk content by ID for stages 2, 3, and 4.
        Avoids re-running retrieval entirely for follow-up turns.
        """
        if not session.anchored_chunk_ids:
            return []

        docs = []
        for chunk_id in session.anchored_chunk_ids:
            doc = self.retrieval_service._fetch_by_id(chunk_id)
            if doc:
                docs.append(doc)

        return docs

    def _deduplicate_across_topics(self, docs: List[Document]) -> List[Document]:
        """
        Removes cross-topic duplicates using first 300 chars as content key.
        Mirrors RetrievalService._deduplicate() to stay consistent.
        """
        seen = set()
        unique = []
        for doc in docs:
            content_key = doc.page_content[:300]
            if content_key not in seen:
                seen.add(content_key)
                unique.append(doc)
        return unique

    def _extract_ids(self, docs: List[Document]) -> List[str]:
        """
        Extracts chunk IDs from document metadata or directly from the Document object.
        """
        ids = []
        for doc in docs:
            # Langchain stores the Chroma ID in the doc.id attribute now
            chunk_id = getattr(doc, "id", None) or doc.metadata.get("chunk_id")
            if chunk_id:
                ids.append(chunk_id)
        return ids