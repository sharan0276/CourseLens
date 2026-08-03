import streamlit as st
import requests

import os
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "http://localhost:8000")

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
    /* Fix Safari list container collapse */
    [data-testid="stChatMessage"] ul {
        width: 100% !important;
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
             messages = data.get("messages", [])
             
             # Apply the URL rewrite to all old messages loaded from history
             for msg in messages:
                 if msg.get("role") == "assistant" and "content" in msg:
                     msg["content"] = msg["content"].replace("CourseLens_data/images/", f"{EXTERNAL_API_URL}/images/")
                     
             return messages
    except requests.exceptions.ConnectionError:
        pass
    return []

def delete_session_from_db(session_id):
    if not session_id:
        return False
    try:
        response = requests.delete(f"{API_BASE_URL}/sessions/{session_id}")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        return False

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

def fetch_recent_logs(limit=5):
    import mlflow
    import json
    from mlflow.tracking import MlflowClient
    
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(mlflow_uri)
    
    try:
        # Check if experiment exists
        exp = mlflow.get_experiment_by_name("courselens-chat")
        if not exp:
            return []
            
        df = mlflow.search_runs(
            experiment_ids=[exp.experiment_id],
            order_by=["attribute.start_time DESC"],
            max_results=limit
        )
        
        if df is None or df.empty:
            return []
            
        client = MlflowClient()
        log_records = []
        
        for _, row in df.iterrows():
            run_id = row.get('run_id')
            audit_data = {}
            try:
                local_path = client.download_artifacts(run_id, "turn_audit_log.json")
                if local_path and os.path.exists(local_path):
                    with open(local_path, 'r') as f:
                        audit_data = json.load(f)
            except Exception:
                pass
                
            log_records.append({
                "run_id": run_id,
                "session_id": row.get('params.session_id', 'Unknown'),
                "query_type": row.get('params.query_type', 'Unknown'),
                "latency_ms": row.get('metrics.latency_ms', 0.0),
                "chunk_count": int(row.get('metrics.chunk_count', 0)) if row.get('metrics.chunk_count') is not None else 0,
                "ta_stage_before": row.get('params.ta_stage_before', '0'),
                "ta_stage_after": row.get('params.ta_stage_after', '0'),
                "selected_topics": row.get('params.selected_topics', ''),
                "user_query": audit_data.get("user_query", row.get('params.query', 'N/A')),
                "bot_response": audit_data.get("bot_response", row.get('params.response', 'N/A')),
                "retrieved_context": audit_data.get("retrieved_context", [])
            })
        return log_records
    except Exception as e:
        print(f"Failed to fetch MLflow logs: {e}")
        return []

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

    tab_chat, tab_logs = st.tabs(["Chat Room", "Live Auditing Logs"])

    with tab_chat:
        if not st.session_state.current_session_id:
            st.info("I am your Socratic AI assistant. Ask me anything about the course materials!")
        
        # Render History
        for msg in st.session_state.chat_history:
            role = msg.get("role", "user")
            with st.chat_message("user" if role == "user" else "assistant"):
                st.markdown(msg.get("content", ""))

    with tab_logs:
        st.write("### MLflow Real-time Run Logs")
        num_logs = st.slider("Logs to retrieve", min_value=5, max_value=50, value=10, step=5, help="Increase to see more history, decrease for faster load times.")
        if st.button("Refresh Logs", use_container_width=True):
            st.rerun()
            
        logs = fetch_recent_logs(limit=num_logs)
        if not logs:
            st.info("No active MLflow runs found. Start chatting to log metrics!")
        else:
            for log in logs:
                title_lbl = f"[{log['query_type']}] {log['user_query'][:40]}... ({int(log['latency_ms'])}ms)"
                with st.expander(title_lbl):
                    st.write(f"**Session ID:** `{log['session_id']}`")
                    st.write(f"**Socratic Stages:** {log['ta_stage_before']} ➡️ {log['ta_stage_after']}")
                    if log['selected_topics']:
                        st.write(f"**Syllabus Topics:** `{log['selected_topics']}`")
                    st.write(f"**Fetched Chunks:** {log['chunk_count']}")
                    
                    st.divider()
                    st.write("**Full Dialogue Turn:**")
                    st.chat_message("user").markdown(log['user_query'])
                    st.chat_message("assistant").markdown(log['bot_response'])
                    
                    if log['retrieved_context']:
                        st.divider()
                        st.write("**Retrieved Slide Context:**")
                        for idx, chunk in enumerate(log['retrieved_context'], 1):
                            src = chunk['metadata'].get('source_file', 'Unknown')
                            slide = chunk['metadata'].get('slide_number', 'N/A')
                            st.write(f"*{idx}. {src} (Slide {slide})*")
                            st.caption(chunk['content'])

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
    
    st.write("**Admin Diagnostics**")
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    st.link_button("Open MLflow Dashboard", mlflow_uri, use_container_width=True, help="Access MLflow runs, latency metrics, and prompt evaluations.")

    st.divider()
    
    if st.button("🗑️ Clear Chat History", type="secondary", use_container_width=True):
        if st.session_state.current_session_id:
            delete_session_from_db(st.session_state.current_session_id)
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
                
                # Rewrite local paths to the FastAPI server URL so Streamlit can fetch them over the network
                ai_text = ai_text.replace("CourseLens_data/images/", f"{EXTERNAL_API_URL}/images/")
                
                session_id = resp_data.get("session_id")
                
                st.markdown(ai_text)
                st.session_state.chat_history.append({"role": "assistant", "content": ai_text})
                
                if st.session_state.current_session_id is None and session_id:
                    st.session_state.current_session_id = session_id
                
                # Force a full page reload for ALL messages (both new and old sessions)
                # This guarantees that Streamlit natively renders local images perfectly from the history loop.
                st.rerun()
