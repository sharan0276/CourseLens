from pydantic import BaseModel

class IngestionRequest(BaseModel):
    """
    Schema for Ingestion Request - Defines the structure of the API request
    """
    folder_path: str


class IngestionResponse(BaseModel):
    """
    Schema for Ingestion Response - Defines the structure of the API response
    """
    files_processed : int
    total_extracted_slides : int
    
