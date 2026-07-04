import os
from langchain_google_vertexai import ChatVertexAI

def _ensure_credentials():
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        gcp_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if gcp_json:
            creds_path = "/tmp/gcp_credentials.json"
            with open(creds_path, "w", encoding="utf-8") as f:
                f.write(gcp_json)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            creds_path = os.path.join(base_dir, "secrets", "gcp_credentials.json")
            if os.path.exists(creds_path):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
            else:
                raise FileNotFoundError(f"File {creds_path} was not found and GOOGLE_APPLICATION_CREDENTIALS_JSON env variable is empty.")

def get_vertex_llm(temperature: float = 0.7) -> ChatVertexAI:
    """
    Returns the primary ChatVertexAI instance (e.g. for heavy lifting/generation).
    """
    _ensure_credentials()
        
    return ChatVertexAI(
        model_name="gemini-2.5-flash",  # Can change this to "gemini-1.5-pro" later
        project="courselens-dev-500606",
        location="us-east1",
        temperature=temperature
    )

def get_vertex_flash_llm(temperature: float = 0.0) -> ChatVertexAI:
    """
    Returns a lightweight ChatVertexAI instance (e.g. for routing/classification).
    """
    _ensure_credentials()
        
    return ChatVertexAI(
        model_name="gemini-2.5-flash",  # Can change this to "gemini-1.5-flash" later
        project="courselens-dev-500606",
        location="us-east1",
        temperature=temperature
    )
