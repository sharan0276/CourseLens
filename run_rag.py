import os
import sys
import argparse

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from services.rag.rag_pipeline import RAGPipeline
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.embedding.embedder import Embedder
from langchain_google_genai import ChatGoogleGenerativeAI

def main():
    parser = argparse.ArgumentParser(description="CourseLens RAG Pipeline")
    parser.add_argument("--ingest", action="store_true", help="Ingest documents into the vector store")
    parser.add_argument("--query", type=str, help="Question to ask the RAG pipeline")
    parser.add_argument("--search-type", type=str, default="similarity", choices=["similarity", "mmr", "similarity_score_threshold"], help="Retrieval method to use")
    
    args = parser.parse_args()

    # Make sure GEMINI_API_KEY is set in environment for Gemini LLM
    if args.query and not os.environ.get("GEMINI_API_KEY"):
        print("Warning: GEMINI_API_KEY environment variable not set. Please set it to use the Google Gemini models for generation.")
        print("Example: export GEMINI_API_KEY='your-key-here'")
        return
        
    print("Initializing RAG Pipeline...")
    
    # Initialize our custom embedder using BAAI/bge-m3
    print("Loading local embeddings model (BAAI/bge-m3)...")
    base_embedder = Embedder()
    embeddings = CourseLensEmbeddings(embedder=base_embedder)
    
    # We are using Google Gemini for generation, but the custom internal Embedder for embeddings
    # Only initialize if we're querying, or if the API key is set
    llm = None
    if args.query or os.environ.get("GEMINI_API_KEY"):
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=os.environ.get("GEMINI_API_KEY", "dummy_key"),
        )
    
    pipeline = RAGPipeline(llm=llm, embeddings=embeddings, search_type=args.search_type,data_dir='CourseLens_data/processed_data')

    if args.ingest:
        pipeline.ingest_data()
        
    if args.query:
        print(f"\nQuestion: {args.query}")
        print("Answer: ", end="", flush=True)
        # We can stream or just print
        answer = pipeline.query(args.query)
        print(answer)

if __name__ == "__main__":
    main()
