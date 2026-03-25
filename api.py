import os
import sys
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager

# Make sure project root is on the path (if running from subdirectories)
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from langchain_google_genai import ChatGoogleGenerativeAI
from services.embedding.embedder import Embedder
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.chat.chat_history import ChatHistoryStore
from services.chat.chat_pipeline import ChatPipeline

SESSIONS_DIR = "CourseLens_data/chat_sessions"

class AppState:
    history_store: ChatHistoryStore
    pipelines: Dict[str, ChatPipeline] = {}

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
        
    print("Loading embedding model (BAAI/bge-m3)...")
    base_embedder = Embedder()
    embeddings = CourseLensEmbeddings(embedder=base_embedder)
    
    print("Initialising LLM (Gemini)...")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
    )
    
    state.history_store = ChatHistoryStore(storage_dir=SESSIONS_DIR)
    
    print("Initializing Chat Pipelines...")
    # Initialize both general and coding pipelines so they are ready
    state.pipelines["general"] = ChatPipeline(
        embeddings=embeddings,
        history_store=state.history_store,
        llm=llm,
        mode="general",
        search_type="similarity"
    )
    state.pipelines["coding"] = ChatPipeline(
        embeddings=embeddings,
        history_store=state.history_store,
        llm=llm,
        mode="coding",
        search_type="similarity"
    )
    
    print("Services initialized successfully.")
    yield

app = FastAPI(
    title="CourseLens Chat API",
    description="API for the CourseLens RAG Chat Session",
    version="1.0.0",
    lifespan=lifespan
)

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    mode: str = "general" # 'general' or 'coding'

class ChatResponse(BaseModel):
    session_id: str
    response: str
    mode: str

class SessionInfo(BaseModel):
    session_id: str
    mode: str
    message_count: int

class ChatMessageOut(BaseModel):
    role: str
    content: str
    timestamp: str

class SessionHistory(BaseModel):
    session_id: str
    mode: str
    messages: List[ChatMessageOut]

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/sessions", response_model=List[SessionInfo])
def list_sessions():
    session_ids = state.history_store.list_sessions()
    result = []
    for sid in session_ids:
        sess = state.history_store.load_session(sid)
        if sess:
            result.append(
                SessionInfo(
                    session_id=sid,
                    mode=sess.mode,
                    message_count=len(sess.messages)
                )
            )
    return result

@app.get("/history/{session_id}", response_model=SessionHistory)
def get_history(session_id: str):
    session = state.history_store.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    msgs = [
        ChatMessageOut(
            role=m.role,
            content=m.content,
            timestamp=m.timestamp.isoformat()
        )
        for m in session.messages
    ]
    return SessionHistory(
        session_id=session.session_id,
        mode=session.mode,
        messages=msgs
    )

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
        
    mode = request.mode if request.mode in ["general", "coding"] else "general"
    
    # 1. Load or Create Session
    if request.session_id:
        session = state.history_store.load_session(request.session_id)
        if not session:
            session = state.history_store.create_session(mode=mode)
    else:
        session = state.history_store.create_session(mode=mode)
        
    # The session might have a different mode than the request, 
    # we'll use the session's actual mode to determine which pipeline to call.
    active_mode = session.mode
    pipeline = state.pipelines.get(active_mode)
    
    if not pipeline:
        raise HTTPException(status_code=500, detail=f"Pipeline for mode '{active_mode}' not configured")
        
    # 2. Process chat
    try:
        reply = pipeline.chat(
            session_id=session.session_id,
            user_input=request.message,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    return ChatResponse(
        session_id=session.session_id,
        response=reply,
        mode=active_mode
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
