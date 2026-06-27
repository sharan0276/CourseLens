import os
import sys
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager

# Make sure project root is on the path (if running from subdirectories)
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services.llm_factory import get_vertex_llm, get_vertex_flash_llm
from services.embedding.embedder import Embedder
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.chat.chat_history import ChatHistoryStore
from services.chat.chat_pipeline import ChatPipeline

# SESSIONS_DIR = "CourseLens_data/chat_sessions" # Removed because we use DynamoDB

class AppState:
    history_store: ChatHistoryStore
    pipeline: ChatPipeline = None
    title_llm: Any = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Loading embedding model (BAAI/bge-m3)...")
    base_embedder = Embedder()
    embeddings = CourseLensEmbeddings(embedder=base_embedder)
    
    print("Initialising LLM (Vertex AI)...")
    llm = get_vertex_llm(temperature=0.7)
    flash_llm = get_vertex_flash_llm(temperature=0.0)
    
    state.title_llm = flash_llm
    state.history_store = ChatHistoryStore()
    
    print("Initializing Unified Chat Pipeline...")
    state.pipeline = ChatPipeline(
        embeddings=embeddings,
        history_store=state.history_store,
        llm=llm,
        flash_llm=flash_llm,
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

# Mount the images directory so they can be accessed via URL
app.mount("/images", StaticFiles(directory="CourseLens_data/images"), name="images")

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    lecture_number: Optional[int] = None  # max lecture to filter retrieval by
    use_web_scraping: bool = True

class ChatResponse(BaseModel):
    session_id: str
    response: str
    mode: str
    lecture_number: Optional[int] = None

class SessionInfo(BaseModel):
    session_id: str
    mode: str
    message_count: int
    title: Optional[str] = None
    created_at: str

class SessionTitleUpdate(BaseModel):
    title: str

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
                    message_count=len(sess.messages),
                    title=sess.title,
                    created_at=sess.created_at.isoformat()
                )
            )
    # Sort from most recent to least recent
    result.sort(key=lambda s: s.created_at, reverse=True)
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

@app.patch("/sessions/{session_id}/title")
def update_session_title(session_id: str, request: SessionTitleUpdate):
    session = state.history_store.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.title = request.title
    state.history_store.save_session(session)
    return {"status": "success", "title": session.title}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
        
    # 1. Load or Create Session
    if request.session_id:
        session = state.history_store.load_session(request.session_id)
        if not session:
            session = state.history_store.create_session(mode="unified")
    else:
        session = state.history_store.create_session(mode="unified")
        
    pipeline = state.pipeline
    
    if not pipeline:
        raise HTTPException(status_code=500, detail="Chat pipeline not initialized")
        
    # 2. Process chat
    try:
        reply = pipeline.chat(
            session_id=session.session_id,
            user_input=request.message,
            lecture_number=request.lecture_number,
            use_web_scraping=request.use_web_scraping
        )
        
        # 3. Auto-generate title if missing
        # Reload session from disk since pipeline.chat modified and saved it
        session = state.history_store.load_session(session.session_id)
        
        if not session.title:
            try:
                title_prompt = f"Generate a short (3 to 5 words) descriptive title for a chat session that starts with this user query: '{request.message}'. Reply ONLY with the title, no quotes or additional text."
                title_resp = state.title_llm.invoke(title_prompt)
                session.title = title_resp.content.strip(' "\'')
                state.history_store.save_session(session)
            except Exception as e:
                print(f"Failed to auto-generate title: {e}")
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    return ChatResponse(
        session_id=session.session_id,
        response=reply,
        mode=session.mode,
        lecture_number=request.lecture_number
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
