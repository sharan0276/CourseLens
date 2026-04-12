#!/usr/bin/env python3
"""
run_chat.py  –  Interactive CLI for the CourseLens Chat Session.

Usage:
  # Start a new general Q&A session
  python run_chat.py

  # Start a new coding (Socratic tutor) session
  python run_chat.py --mode coding

  # Resume an existing session
  python run_chat.py --session <session_id>

  # List all saved session IDs
  python run_chat.py --list

  # Ingest data first, then start a session
  python run_chat.py --ingest

Type 'exit' or 'quit' (or Ctrl-C) to end the session.
"""

import os
import sys
import re
import argparse

# Make sure project root is on the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from langchain_google_genai import ChatGoogleGenerativeAI

from services.embedding.embedder import Embedder
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.rag.vector_store import VectorStoreManager
from services.rag.loader import JSONSlideLoader
from services.chat.chat_history import ChatHistoryStore
from services.chat.chat_pipeline import ChatPipeline
from services.chat.citation_utils import add_sources_footer

# ── Constants ─────────────────────────────────────────────────────────────────

DATA_DIR     = "CourseLens_data/processed_data"
PERSIST_DIR  = "CourseLens_data/chroma_db"
SESSIONS_DIR = "CourseLens_data/chat_sessions"

BANNER = """
╔══════════════════════════════════════════╗
║          CourseLens Chat Session         ║
╚══════════════════════════════════════════╝
Type your question and press Enter.
Type 'exit' or 'quit' to end the session.
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print(
            "Error: GEMINI_API_KEY environment variable is not set.\n"
            "Export it first:  export GEMINI_API_KEY='your-key-here'"
        )
        sys.exit(1)
    return key


def _build_dependencies(api_key: str, mode: str, search_type: str):
    """Initialise all shared services and return (pipeline, history_store)."""

    print("Loading embedding model (BAAI/bge-m3) …")
    base_embedder = Embedder()
    embeddings    = CourseLensEmbeddings(embedder=base_embedder)

    print("Initialising LLM (Gemini) …")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
    )
    
    flash_llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",        # lightweight model for classification & assessment
        google_api_key=api_key,
        temperature=0,                    # deterministic — always picks most likely label
    )

    history_store = ChatHistoryStore(storage_dir=SESSIONS_DIR)

    pipeline = ChatPipeline(
        embeddings=embeddings,
        history_store=history_store,
        llm=llm,
        flash_llm=flash_llm,
        mode=mode,
        search_type=search_type,
    )

    return pipeline, history_store


def _ingest(embeddings):
    """Load JSON files into the Chroma vector store."""
    loader       = JSONSlideLoader(data_dir=DATA_DIR)
    vector_store = VectorStoreManager(
        embeddings_model=embeddings,
        persist_directory=PERSIST_DIR,
    )
    print("Loading documents …")
    docs = loader.load()
    if docs:
        print(f"Loaded {len(docs)} documents. Adding to vector store …")
        vector_store.add_documents(docs)
        print("Ingestion complete.")
    else:
        print("No documents found to ingest.")


def _print_history(history_store: ChatHistoryStore, session_id: str):
    """Print prior conversation turns when resuming a session."""
    session = history_store.load_session(session_id)
    if not session or not session.messages:
        return
    print("\n── Previous conversation ──────────────────────────")
    if session.history_summary:
        print(f"\n[Summary of Older Messages]\n{session.history_summary}")

    for msg in session.messages[session.summary_index:]:
        prefix = "You:" if msg.role == "user" else "CourseLens:"
        print(f"\n{prefix}\n{msg.content}")
    print("── End of history ─────────────────────────────────\n")



# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CourseLens interactive chat session",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode", choices=["general", "coding"], default="general",
        help="Pipeline mode: 'general' for Q&A, 'coding' for Socratic tutor (default: general).",
    )
    parser.add_argument(
        "--session", type=str, default=None,
        help="Resume an existing session by its ID.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all saved session IDs and exit.",
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="Ingest processed course data into the vector store before chatting.",
    )
    parser.add_argument(
        "--search-type", type=str, default="similarity",
        choices=["similarity", "mmr", "similarity_score_threshold"],
        help="Retrieval method (default: similarity).",
    )
    parser.add_argument(
        "--stream", action="store_true",
        help="Stream assistant responses token-by-token.",
    )
    args = parser.parse_args()

    # ── --list ────────────────────────────────────────────────────────────────
    if args.list:
        store    = ChatHistoryStore(storage_dir=SESSIONS_DIR)
        sessions = store.list_sessions()
        if sessions:
            print("Saved sessions:")
            for sid in sessions:
                sess = store.load_session(sid)
                n    = len(sess.messages) if sess else "?"
                mode = sess.mode if sess else "?"
                print(f"  {sid}  [{mode}]  ({n} messages)")
        else:
            print("No saved sessions found.")
        return

    api_key = _check_api_key()

    # ── --ingest ──────────────────────────────────────────────────────────────
    if args.ingest:
        print("Loading embedding model for ingestion …")
        base_embedder = Embedder()
        embeddings    = CourseLensEmbeddings(embedder=base_embedder)
        _ingest(embeddings)

    # ── Build pipeline ────────────────────────────────────────────────────────
    pipeline, history_store = _build_dependencies(
        api_key=api_key,
        mode=args.mode,
        search_type=args.search_type,
    )

    # ── Session setup ─────────────────────────────────────────────────────────
    if args.session:
        session = history_store.load_session(args.session)
        if session is None:
            print(f"Session '{args.session}' not found. Starting a new session instead.")
            session = history_store.create_session(mode=args.mode)
        else:
            print(f"Resuming session: {session.session_id}  [{session.mode} mode]")
            _print_history(history_store, session.session_id)
    else:
        session = history_store.create_session(mode=args.mode)
        print(f"New session started: {session.session_id}  [{args.mode} mode]")

    print(BANNER)

    # ── REPL ──────────────────────────────────────────────────────────────────
    try:
        print("\n(Multi-line input enabled. Press Enter, then Ctrl-D on a new line to submit.)")
        
        print("\nMax lecture number to filter by (press Enter for all): ", end="", flush=True)
        lecture_input = input().strip()
        lecture_number = None
        if lecture_input.isdigit():
            lecture_number = int(lecture_input)

        while True:
            print("You:")
            lines = []
            try:
                while True:
                    lines.append(input())
            except EOFError:
                pass
            
            user_input = "\n".join(lines).strip()
            
            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit"}:
                print("Ending session. Goodbye!")
                break

            print("\nCourseLens: ", end="", flush=True)

            try:
                if args.stream:
                    for chunk in pipeline.chat_stream(session.session_id, user_input, lecture_number=lecture_number):
                        print(chunk, end="", flush=True)
                    print("\n")
                else:
                    reply = pipeline.chat(session.session_id, user_input, lecture_number=lecture_number)
                    print(reply, "\n")

            except Exception as e:
                print(f"\n[Error] {e}\n")

    except KeyboardInterrupt:
        print("\n\nSession interrupted. Goodbye!")

    print(f"\nSession ID: {session.session_id}")
    print("Resume later with:")
    print(f"  python run_chat.py --session {session.session_id}")


if __name__ == "__main__":
    main()
