import os
import sys
import argparse

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from services.rag.rag_pipeline import RAGPipeline
from services.rag.rag_pipeline_coding import RAGPipelineCoding
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.embedding.embedder import Embedder
from services.session.session_store import SessionStore
from services.session.chat_session import ChatSession
from langchain_google_genai import ChatGoogleGenerativeAI


def build_llm():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Example: export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)


def build_embeddings():
    print("Loading local embeddings model (BAAI/bge-m3)...")
    base_embedder = Embedder()
    return CourseLensEmbeddings(embedder=base_embedder)


def main():
    parser = argparse.ArgumentParser(description="CourseLens RAG Pipeline")

    # ── Existing flags ────────────────────────────────────────────────────────
    parser.add_argument("--query", type=str, help="Question to ask the RAG pipeline (single-turn)")
    parser.add_argument("--debug", type=str, help="C++ code/error to debug using the coding RAG pipeline (single-turn)")
    parser.add_argument("--search-type", type=str, default="similarity",
                        choices=["similarity", "mmr", "similarity_score_threshold"],
                        help="Retrieval method to use")
    parser.add_argument("--lecture_number", type=int, default=None, help="Lecture number to filter by")

    # ── Session flags ─────────────────────────────────────────────────────────
    parser.add_argument("--new-session", action="store_true",
                        help="Create a new chat session and print its ID")
    parser.add_argument("--new-debug-session", action="store_true",
                        help="Create a new coding/debug chat session and print its ID")
    parser.add_argument("--session", type=str, metavar="SESSION_ID",
                        help="Session ID to use for a multi-turn query (use with --query or --debug)")
    parser.add_argument("--list-sessions", action="store_true",
                        help="List all chat sessions")
    parser.add_argument("--delete-session", type=str, metavar="SESSION_ID",
                        help="Delete a chat session by ID")

    args = parser.parse_args()

    store = SessionStore()  # shared JSON store at CourseLens_data/chat_sessions.json

    # ── Session management (no LLM needed) ────────────────────────────────────

    if args.new_session:
        sid = store.create_session(pipeline_type="general")
        print(f"New general session created: {sid}")
        return

    if args.new_debug_session:
        sid = store.create_session(pipeline_type="coding")
        print(f"New coding/debug session created: {sid}")
        return

    if args.list_sessions:
        sessions = store.list_sessions()
        if not sessions:
            print("No sessions found.")
        else:
            print(f"{'Session ID':<40} {'Type':<10} {'Turns'}")
            print("-" * 60)
            for s in sessions:
                print(f"{s['session_id']:<40} {s['pipeline_type']:<10} {s['turns']}")
        return

    if args.delete_session:
        removed = store.delete_session(args.delete_session)
        if removed:
            print(f"Session '{args.delete_session}' deleted.")
        else:
            print(f"Session '{args.delete_session}' not found.")
        return

    # ── Build shared components ────────────────────────────────────────────────
    print("Initializing RAG Pipeline...")
    embeddings = build_embeddings()

    # ── Session-based multi-turn chat ─────────────────────────────────────────

    if args.session:
        session_info = store.get_session(args.session)
        if session_info is None:
            print(f"Error: Session '{args.session}' not found. Create one with --new-session.")
            sys.exit(1)

        llm = build_llm()
        pipeline_type = session_info.get("pipeline_type", "general")

        if pipeline_type == "coding":
            pipeline = RAGPipelineCoding(llm=llm, embeddings=embeddings,
                                         search_type=args.search_type,
                                         data_dir="CourseLens_data/processed_data")
        else:
            pipeline = RAGPipeline(llm=llm, embeddings=embeddings,
                                   search_type=args.search_type,
                                   data_dir="CourseLens_data/processed_data")

        chat = ChatSession(pipeline=pipeline, session_store=store)

        message = args.query or args.debug
        if not message:
            print("Error: Provide a message with --query or --debug when using --session.")
            sys.exit(1)

        print(f"\nYou: {message}")
        print("Assistant: ", end="", flush=True)
        reply = chat.send_message(args.session, message)
        print(reply)
        turns = len(store.get_history(args.session)) // 2
        print(f"\n[Session {args.session[:8]}... | {turns} turn(s) stored]")
        return

    # ── Original single-turn flow ─────────────────────────────────────────────

    llm = None
    if args.query or args.debug or os.environ.get("GEMINI_API_KEY"):
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=os.environ.get("GEMINI_API_KEY", "dummy_key"),
        )

    if args.debug:
        pipeline = RAGPipelineCoding(llm=llm, embeddings=embeddings,
                                     search_type=args.search_type,
                                     data_dir="CourseLens_data/processed_data")
        print(f"\nDebugging Query:\n{args.debug}")
        print("\nCourseLens Debug Assistant: ", end="", flush=True)
        print(pipeline.query(args.debug))

    else:
        pipeline = RAGPipeline(llm=llm, embeddings=embeddings, search_type=args.search_type)

        
    if args.query:
        print(f"\nQuestion: {args.query}")
        print("Answer: ", end="", flush=True)
        # We can stream or just print
        lecture_num = getattr(args, 'lecture_number', None)
        answer = pipeline.query(args.query, lecture_number=lecture_num)
        print(answer)

if __name__ == "__main__":
    main()
