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

class RAGPipeline:
    def __init__(self, llm: BaseChatModel, embeddings: Embeddings, data_dir: str = "CourseLens_data/processed_data/", persist_dir: str = "CourseLens_data/chroma_db", search_type: str = "similarity"):
        self.llm = llm
        self.embeddings = embeddings
        
        self.loader = JSONSlideLoader(data_dir=data_dir)
        self.vector_store = VectorStoreManager(embeddings_model=self.embeddings, persist_directory=persist_dir)
        self.search_type = search_type
        
        # Define the system prompt
        system_prompt = (
            "You are an assistant for question-answering tasks based on course materials.\n"
            "Use the following pieces of retrieved context to answer the user's question.\n"
            "If you don't know the answer, just say that you don't know.\n"
            "Use three sentences maximum and keep the answer concise.\n"
            "\nContext:\n{context}"
        )

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        
        self.chain = self._build_chain()
        
    def _format_docs(self, docs):
        return "\n\n".join(doc.page_content for doc in docs)
        
    def _build_chain(self):
        # Allow retrieving more documents for better parent/child context
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
        response = self.chain.invoke(question)
        return response
        
    def query_stream(self, question: str) -> Generator[str, None, None]:
        """Queries the RAG pipeline and streams the answer."""
        for chunk in self.chain.stream(question):
            yield chunk
