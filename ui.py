import streamlit as st
import requests

API_BASE_URL = "http://localhost:8000"

st.set_page_config(
    page_title="CourseLens Chat",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM STYLING ---
st.markdown("""
<style>
    /* Target images inside chat messages only */
    [data-testid="stChatMessage"] img {
        display: block !important;
        margin-left: auto !important;
        margin-right: auto !important;
        max-width: 85% !important;
        max-height: 400px !important;
        object-fit: contain;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin-top: 15px;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state variables if not present
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

def reset_session():
    """Callback to clear the current session and history."""
    st.session_state.current_session_id = None
    st.session_state.chat_history = []

def on_lecture_change():
    """Triggered when the curriculum filter values change."""
    # Sync the fresh value from the widget key before resetting
    if "lecture_selector" in st.session_state:
        st.session_state.lecture_number = st.session_state.lecture_selector
    reset_session()
    st.session_state.lecture_updated = True

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

def send_message(session_id, message, lecture_number, use_web_scraping=True):
    payload = {
        "session_id": session_id,
        "message": message,
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

# --- SIDEBAR (History) ---
with st.sidebar:
    st.title("📚 CourseLens")
    st.divider()
    
    st.subheader("History")
    if st.button("➕ New Conversation", use_container_width=True):
        st.session_state.current_session_id = None
        st.session_state.chat_history = []
        st.rerun()
        
    sessions = load_sessions()
    if sessions:
        for sess in sessions: 
             sid = sess["session_id"]
             display_name = sess.get("title") or f"{sid[:8]}..."
             label = f"{display_name} ({sess['message_count']} msgs)"
             is_current = sid == st.session_state.current_session_id
             if st.button(label, key=sid, type="primary" if is_current else "secondary", use_container_width=True):
                  st.session_state.current_session_id = sid
                  st.session_state.chat_history = load_history(sid)
                  st.rerun()

# --- MAIN LAYOUT ---
# Initialize session specific settings
if "lecture_number" not in st.session_state:
    st.session_state.lecture_number = 14
if "use_lecture" not in st.session_state:
    st.session_state.use_lecture = True
if "use_web_scraping" not in st.session_state:
    st.session_state.use_web_scraping = True
if "lecture_updated" not in st.session_state:
    st.session_state.lecture_updated = False

# Show notification if curriculum was just updated
if st.session_state.lecture_updated:
    status_msg = f"Curriculum updated! Starting a fresh session"
    if st.session_state.use_lecture:
        status_msg += f" (Up to Lecture {st.session_state.lecture_number})"
    st.toast(status_msg, icon="📚")
    st.session_state.lecture_updated = False

# Split main area into Chat and Control Center
chat_col, control_col = st.columns([7, 3], gap="large")

with chat_col:
    active_session_data = next((s for s in load_sessions() if s["session_id"] == st.session_state.current_session_id), None)
    active_title = active_session_data.get("title") if active_session_data else None
    
    if st.session_state.current_session_id:
        st.title(active_title if active_title else f"Session: {st.session_state.current_session_id[:8]}")
    else:
        st.title("CourseLens Tutor")
        st.info("I am your Socratic AI assistant. Ask me anything about the course materials!")

    # Render History
    for msg in st.session_state.chat_history:
        role = msg.get("role", "user")
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(msg.get("content", ""))

with control_col:
    st.subheader("🛠️ Control Center")
    st.write("Configure your learning experience for this session.")
    
    with st.container(border=True):
        st.write("**Session Details**")
        if st.session_state.current_session_id:
            updated_title = st.text_input("Edit Title", value=active_title or "", placeholder="Enter a descriptive title...")
            if st.button("Update Title", use_container_width=True):
                if update_session_title(st.session_state.current_session_id, updated_title):
                    st.success("Title updated!")
                    st.rerun()
            st.caption(f"ID: `{st.session_state.current_session_id}`")
        else:
            st.caption("Start a chat to edit session details.")

    st.divider()
    
    st.write("**Pedagogical Logic**")
    st.session_state.use_web_scraping = st.toggle("🌐 Enable Web Research", value=st.session_state.use_web_scraping, help="If enabled, the tutor will supplement course slides with trusted web references (LearnCpp, etc.)")
    
    st.write("**Course Progress**")
    st.session_state.lecture_number = st.number_input(
        "Current Week / Lecture", 
        min_value=1, 
        max_value=14, 
        step=1, 
        value=st.session_state.lecture_number, 
        key="lecture_selector",
        on_change=on_lecture_change,
        help="The tutor will only use materials up to this lecture. Adjust this as you progress through the course."
    )

    st.divider()
    
    if st.button("🗑️ Clear Chat History", type="secondary", use_container_width=True):
        reset_session()
        st.rerun()



# --- INPUT AREA (Pinned to Global Bottom) ---
# Calling this at the very end of the script outside any columns/containers 
# is the most reliable way to ensure it pins to the absolute bottom of the viewport.
user_input = st.chat_input("Ask a question about the course materials...")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    
    # We render the new messages into the main chat column
    with chat_col:
        with st.chat_message("user"):
            st.markdown(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("Analyzing materials..."):
                resp_data = send_message(
                    session_id=st.session_state.current_session_id,
                    message=user_input,
                    lecture_number=st.session_state.lecture_number,
                    use_web_scraping=st.session_state.use_web_scraping
                )
            
            if resp_data:
                ai_text = resp_data.get("response", "")
                ai_text = ai_text.replace("CourseLens_data/images/", f"{API_BASE_URL}/images/")
                session_id = resp_data.get("session_id")
                
                st.markdown(ai_text)
                st.session_state.chat_history.append({"role": "assistant", "content": ai_text})
                
                if st.session_state.current_session_id is None and session_id:
                    st.session_state.current_session_id = session_id
                    st.rerun()
