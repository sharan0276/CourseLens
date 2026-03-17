import os
import sys

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from services.rag.rag_pipeline import RAGPipeline
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.embedding.embedder import Embedder
from langchain_google_genai import ChatGoogleGenerativeAI
from services.rag.retrieval_service import RetrievalService
from services.rag.chroma_retriever import VectorStoreManager

os.environ["GEMINI_API_KEY"] = "dummy_key" # API key not needed for just retrieval testing

print("Loading local embeddings model (BAAI/bge-m3)...")
base_embedder = Embedder()
embeddings = CourseLensEmbeddings(embedder=base_embedder)
vector_store = VectorStoreManager(embeddings_model=embeddings, persist_directory="CourseLens_data/chroma_db", collection_name="course_lens")
retrieval_service = RetrievalService(vector_store_manager=vector_store, db_path="CourseLens_data/chroma_db", collection_name="course_lens", k=5)

docs = retrieval_service.retrieve("Explain Computer Organization?")

print("\n--- FORMATTED DOCS STRING FOR LLM ---")
pipeline = RAGPipeline(llm=None, embeddings=embeddings)
formatted = pipeline._format_docs(docs)
print(formatted)
