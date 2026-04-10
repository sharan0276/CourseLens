import streamlit as st
import requests

API_BASE_URL = "http://localhost:8000"

st.set_page_config(
    page_title="CourseLens Chat",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state variables if not present
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "session_mode" not in st.session_state:
    st.session_state.session_mode = "general"

def load_sessions():
    try:
        response = requests.get(f"{API_BASE_URL}/sessions")
        if response.status_code == 200:
            return response.json()
        st.error(f"Failed to load sessions: {response.status_code}")
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to backend API. Please ensure FastAPI is running.")
    return []

def load_history(session_id):
    if not session_id:
        return []
    try:
        response = requests.get(f"{API_BASE_URL}/history/{session_id}")
        if response.status_code == 200:
             data = response.json()
             return data.get("messages", [])
    except requests.exceptions.ConnectionError:
        pass
    return []

def send_message(session_id, message, mode, lecture_number, use_web_scraping=True):
    payload = {
        "session_id": session_id,
        "message": message,
        "mode": mode,
        "use_web_scraping": use_web_scraping
    }
    if lecture_number is not None:
        payload["lecture_number"] = lecture_number
        
    try:
        response = requests.post(f"{API_BASE_URL}/chat", json=payload)
        if response.status_code == 200:
            return response.json()
        st.error(f"API Error {response.status_code}: {response.text}")
    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to the backend API.")
    return None

def update_session_title(session_id, new_title):
    try:
        response = requests.patch(f"{API_BASE_URL}/sessions/{session_id}/title", json={"title": new_title})
        if response.status_code == 200:
            return True
        st.error(f"Failed to update title: {response.text}")
    except requests.exceptions.ConnectionError:
         st.error("Failed to connect to the backend API.")
    return False

# --- SIDEBAR ---
with st.sidebar:
    st.title("📚 CourseLens")
    
    st.subheader("Settings")
    mode = st.radio("Chat Mode", ["general", "coding"], index=["general", "coding"].index(st.session_state.session_mode))
    # Update state if changed
    if mode != st.session_state.session_mode:
         st.session_state.session_mode = mode
         
    st.divider()
    
    st.subheader("Sessions")
    if st.button("➕ New Session", use_container_width=True):
        st.session_state.current_session_id = None
        st.session_state.chat_history = []
        st.rerun()
        
    sessions = load_sessions()
    if sessions:
        # Sessions are returned natively sorted from most recent to least recent by the backend
        for sess in sessions: 
             sid = sess["session_id"]
             display_name = sess.get("title") or f"{sid[:8]}..."
             label = f"[{sess['mode']}] {display_name} ({sess['message_count']} msgs)"
             # Highlight current session
             is_current = sid == st.session_state.current_session_id
             if st.button(label, key=sid, type="primary" if is_current else "secondary", use_container_width=True):
                  st.session_state.current_session_id = sid
                  st.session_state.session_mode = sess["mode"]
                  st.session_state.chat_history = load_history(sid)
                  st.rerun()

# --- MAIN CHAT AREA ---
# Retrieve active session details for header
active_session_data = next((s for s in load_sessions() if s["session_id"] == st.session_state.current_session_id), None)
active_title = active_session_data.get("title") if active_session_data else None

# Default lecture state per UI refresh
if "lecture_number" not in st.session_state:
    st.session_state.lecture_number = None
if "use_lecture" not in st.session_state:
    st.session_state.use_lecture = False
if "use_web_scraping" not in st.session_state:
    st.session_state.use_web_scraping = True

if st.session_state.current_session_id:
    col1, col2 = st.columns([8, 2])
    with col1:
        st.header(active_title if active_title else f"Chat Session: `{st.session_state.current_session_id[:8]}...`")
    with col2:
        with st.popover("⚙️ Chat Settings", use_container_width=True):
            new_title = st.text_input("Session Title", value=active_title or "")
            if st.button("Save Title"):
                if update_session_title(st.session_state.current_session_id, new_title):
                    st.success("Saved!")
                    st.rerun()
            st.divider()
            st.session_state.use_web_scraping = st.checkbox("Enable Webscraping", value=st.session_state.use_web_scraping)
            
            st.session_state.use_lecture = st.checkbox("Filter by Lecture", value=st.session_state.use_lecture)
            if st.session_state.use_lecture:
                 st.session_state.lecture_number = st.number_input("Max Lecture", min_value=1, step=1, value=st.session_state.lecture_number or 5)
            else:
                 st.session_state.lecture_number = None
else:
    st.header("CourseLens Chat")
    st.markdown("Start typing below to begin a new conversation!")
    
    with st.popover("⚙️ Initial Settings"):
        st.session_state.use_web_scraping = st.checkbox("Enable Webscraping", value=st.session_state.use_web_scraping)
        st.session_state.use_lecture = st.checkbox("Filter by Lecture Max", value=st.session_state.use_lecture)
        if st.session_state.use_lecture:
            st.session_state.lecture_number = st.number_input("Max Lecture Number", min_value=1, value=5, step=1)
        else:
            st.session_state.lecture_number = None

# Render History
for msg in st.session_state.chat_history:
    role = msg.get("role", "user")
    # Streamlit uses "user" and "assistant" roles natively for avatars
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(msg.get("content", ""))

# Input
user_input = st.chat_input("Ask a question about the course materials...")

if user_input:
    # 1. Show user message
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
         st.markdown(user_input)
         
    # 2. Call backend
    with st.chat_message("assistant"):
         with st.spinner("Thinking..."):
             resp_data = send_message(
                 session_id=st.session_state.current_session_id,
                 message=user_input,
                 mode=st.session_state.session_mode,
                 lecture_number=st.session_state.lecture_number,
                 use_web_scraping=st.session_state.use_web_scraping
             )
         
         if resp_data:
             ai_text = resp_data.get("response", "")
             session_id = resp_data.get("session_id")
             
             st.markdown(ai_text)
             
             # Append to history
             st.session_state.chat_history.append({"role": "assistant", "content": ai_text})
             
             # If it was a new session, update ID and refresh sidebar
             if st.session_state.current_session_id is None and session_id:
                  st.session_state.current_session_id = session_id
                  st.rerun()
