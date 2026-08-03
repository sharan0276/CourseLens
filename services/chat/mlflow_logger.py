import os
import time
import mlflow
import contextvars
from typing import List, Dict

# Thread-safe and async-safe context variable to store retrieved docs during a single request/turn
retrieved_docs_var = contextvars.ContextVar("retrieved_docs", default=[])

class MLflowLogger:
    """Handles logging of chatbot performance, state transitions, and retrieval metrics in MLflow."""
    
    _initialized = False

    @classmethod
    def initialize(cls):
        """Initializes the MLflow configuration from environment variables."""
        if cls._initialized:
            return
            
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
        experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "courselens-chat")
        
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)
        cls._initialized = True
        print(f"[MLflow] Connected to Tracking Server at: {tracking_uri}")

    @classmethod
    def log_turn(cls, 
                 session_id: str, 
                 query: str, 
                 response: str, 
                 query_type: str, 
                 latency_ms: float, 
                 ta_stage_before: int,
                 ta_stage_after: int,
                 retrieved_chunks: List,  # list of LangChain Document objects
                 selected_topics: List[str] = None):
        """Records a single conversational turn in MLflow."""
        try:
            cls.initialize()
            
            # Start a run for this specific turn
            with mlflow.start_run(run_name=f"turn-{int(time.time())}"):
                # 1. Log metadata parameters to RDS
                mlflow.log_param("session_id", session_id)
                mlflow.log_param("query_type", query_type)
                mlflow.log_param("ta_stage_before", ta_stage_before)
                mlflow.log_param("ta_stage_after", ta_stage_after)
                
                if selected_topics:
                    mlflow.log_param("selected_topics", ",".join(selected_topics))
                
                # 2. Log speed and count metrics to RDS
                mlflow.log_metric("latency_ms", latency_ms)
                mlflow.log_metric("chunk_count", len(retrieved_chunks))
                mlflow.log_metric("is_socratic_loop", 1 if ta_stage_after in [2, 3] else 0)
                
                # 3. Log quick reference tags to RDS
                mlflow.set_tag("source", "user_chat")
                slide_citations = []
                for doc in retrieved_chunks:
                    source = doc.metadata.get("source_file", "Unknown")
                    slide = doc.metadata.get("slide_number", "None")
                    slide_citations.append(f"{source}-slide{slide}")
                
                if slide_citations:
                    # Deduplicate citations to keep string short and clean
                    unique_citations = list(set(slide_citations))
                    mlflow.set_tag("retrieved_slides", ",".join(unique_citations[:5])) # limit tag size
                
                # 4. Upload heavy transcripts and raw context to S3 as a JSON artifact
                turn_details = {
                    "session_id": session_id,
                    "user_query": query,
                    "bot_response": response,
                    "retrieved_context": [
                        {
                            "content": doc.page_content,
                            "metadata": doc.metadata
                        } for doc in retrieved_chunks
                    ]
                }
                mlflow.log_dict(turn_details, "turn_audit_log.json")
                print(f"[MLflow] Logged turn successfully for session {session_id}")
                
        except Exception as e:
            # We catch exceptions so that if the MLflow server is down,
            # the student's chatbot session doesn't crash!
            print(f"[MLflow Warning] Logging failed: {e}")
