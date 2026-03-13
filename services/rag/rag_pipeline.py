from typing import List, Generator
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser

from services.rag.retrieval_service import RetrievalService
from services.rag.chroma_retriever import VectorStoreManager

class RAGPipeline:
    def __init__(self, llm: BaseChatModel, embeddings: Embeddings, persist_dir: str = "CourseLens_data/chroma_db",
                 collection_name: str = "course_lens", search_type: str = "similarity", k: int = 5):
        self.llm = llm
        
        # vector store - read only setup
        self.vector_store = VectorStoreManager(embeddings_model=embeddings, persist_directory=persist_dir, collection_name = collection_name)

        # retrieval service - handles retrieval and enrichment of chunks
        self.retrieval_service = RetrievalService(vector_store_manager=self.vector_store, db_path=persist_dir, collection_name=collection_name, k=k)

        #self.search_type = search_type
        
        # Define the system prompt
        '''system_prompt = (
            "You are an assistant for question-answering tasks based on course materials.\n"
            "Use the following pieces of retrieved context to answer the user's question.\n"
            "If you don't know the answer, just say that you don't know.\n"
            "Use three sentences maximum and keep the answer concise.\n"
            "Always cite the best matching slide number and source file at the end of your answer.\n"            
            "\nContext:\n{context}"
        )'''

        system_prompt = (
            "You are an assistant for question-answering tasks based on course materials.\n"
            "Use the following pieces of retrieved context to answer the user's question.\n"
            "If you don't know the answer, just say that you don't know.\n"
            "Use ten sentences maximum and keep the answer concise.\n"
            "Every factual claim MUST be followed by a citation in the form [N]. If a claim draws from multiple sources, cite all of them: [1][3].\n"
            "At the end, always include a 'Sources Used' section listing every citation number you used with its source file and title.\n"
            "IMPORTANT: If a retrieved document contains 'Attached Images: <filename>', and the image is relevant to your answer, you MUST include it in your response using markdown syntax: `![Image Description](CourseLens_data/images/<filename>)`\n"
            "\nContext:\n{context}"
        )

        self.search_type = search_type

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        
        self.chain = self._build_chain()
        
    def _format_docs(self, docs: List[Document]) -> str:
        """Formats documents with slide citations for model input."""
        formatted_docs = []
        for doc in docs:
            source_file = doc.metadata.get("source_file", "Unknown")
            slide_number = doc.metadata.get("slide_number", "")
            title = doc.metadata.get("title", "")
            lecture_number = doc.metadata.get("lecture_number", "")
            chunk_type = doc.metadata.get("chunk_type", "")
            image_filenames = doc.metadata.get("image_filenames", "")

            if chunk_type == "parent":
                citation =f"Source: {source_file}, Title: {title}"
            else:
                citation = f"Source: {source_file}, Title: {title}, Slide: {slide_number}"

            if image_filenames:
                # Replace .emf with .png since they are converted during ingestion
                image_filenames = image_filenames.replace(".emf", ".png")
                citation += f", Attached Images: {image_filenames}"

            formatted_docs.append(f"{citation}\n{doc.page_content}")
        
        return "\n\n".join(formatted_docs)
        
    def _build_chain(self):
        # Allow retrieving more documents for better parent/child context
        #retriever = self.vector_store.get_retriever(search_type=self.search_type, k=5)
        
        def retrieve_with_filter(inputs):
            query = inputs["question"]
            lecture_number = inputs.get("lecture_number")
            return self.retrieval_service.retrieve(query, lecture_number=lecture_number)
            
        retriever_template = RunnableLambda(retrieve_with_filter)
        rag_chain = (
            {"context": retriever_template | RunnableLambda(self._format_docs), "input": RunnableLambda(lambda x: x["question"])}
            | self.prompt
            | self.llm
            | StrOutputParser()
        )
        return rag_chain

    def query(self, question: str, lecture_number: int = None) -> str:
        """Queries the RAG pipeline and returns the answer."""
        response = self.chain.invoke({"question": question, "lecture_number": lecture_number})
        return response
        
    def query_stream(self, question: str) -> Generator[str, None, None]:
        """Queries the RAG pipeline and streams the answer."""
        for chunk in self.chain.stream(question):
            yield chunk


'''    def ingest_data(self) -> None:
        """Loads data from the JSON directory and stores it in the vector DB."""
        print("Loading documents using ChunkBuilder...")
        docs = self.loader.load()
        if docs:
            print(f"Loaded {len(docs)} documents. Adding to vector store...")
            self.vector_store.add_documents(docs)
            print("Ingestion complete.")
        else:
            print("No documents found to ingest.")
'''
