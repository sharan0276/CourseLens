import os
from langchain_google_vertexai import ChatVertexAI

def _ensure_credentials():
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        creds_path = os.path.join(base_dir, "secrets", "gcp_credentials.json")
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

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
