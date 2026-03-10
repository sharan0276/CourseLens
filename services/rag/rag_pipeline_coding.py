import os
from typing import List, Generator
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

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

        # System prompt: grounded in course material, beginner-friendly debugging
        system_prompt = (
            "You are CourseLens, a C++ debugging assistant for an introductory programming course.\n"
            "Your job is to help students understand and fix errors in their C++ code.\n\n"
            "When a student shares code with an error, follow these steps:\n"
            "1. Identify the error type (compilation, runtime, logic, etc.)\n"
            "2. Explain WHY the error occurred in simple terms a beginner can understand.\n"
            "3. Ground your explanation in the course material provided in the context below — "
            "reference specific slides or topics the student has already covered when relevant.\n"
            "4. Suggest a fix using only concepts the student has already learned per the course slides.\n"
            "5. Do not just give the answer — guide the student toward understanding.\n\n"
            "If the question is not about debugging or C++, answer using the course context as normal.\n"
            "If the answer is not in the context, say you don't know rather than guessing.\n"
            "Always cite the most relevant slide number and source file at the end of your response.\n\n"
            "Course Material Context:\n{context}"
        )

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        self.chain = self._build_chain()

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
        """Queries the RAG pipeline and returns the answer."""
        return self.chain.invoke(question)

    def query_stream(self, question: str) -> Generator[str, None, None]:
        """Queries the RAG pipeline and streams the answer."""
        for chunk in self.chain.stream(question):
            yield chunk