import os
import json
from typing import List, Dict, Optional

class SyllabusLoader:
    """
    Loads and parses the syllabus topics JSON configuration.
    Provides methods to fetch topics for a specific lecture or all lectures up to a given point.
    """
    
    _instance = None
    _topics_data: Dict[str, Dict[str, List[str]]] = {}
    
    def __new__(cls, config_path: str = "config/syllabus_topics.json"):
        if cls._instance is None:
            cls._instance = super(SyllabusLoader, cls).__new__(cls)
            cls._instance._load_config(config_path)
        return cls._instance

    def _load_config(self, config_path: str) -> None:
        """Loads the JSON file containing the syllabus topics from S3 or local disk."""
        bucket_name = os.getenv("S3_BUCKET_NAME")
        if bucket_name:
            try:
                import boto3
                s3 = boto3.client("s3")
                response = s3.get_object(Bucket=bucket_name, Key=config_path)
                self._topics_data = json.loads(response["Body"].read().decode("utf-8"))
                print("SyllabusLoader: Successfully loaded syllabus topics from S3.")
                return
            except Exception as e:
                print(f"SyllabusLoader: Failed to load from S3: {e}. Falling back to local file.")

        if not os.path.exists(config_path):
            print(f"Warning: Syllabus config not found at {config_path}")
            self._topics_data = {}
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._topics_data = json.load(f)
        except Exception as e:
            print(f"Error loading syllabus config: {e}")
            self._topics_data = {}

    def get_topics(self, lec_number: int) -> List[str]:
        """
        Returns a list of topic strings for the specified lecture number.
        Handles missing lecture numbers gracefully by returning an empty list.
        """
        lec_str = str(lec_number)
        if lec_str in self._topics_data and "topics" in self._topics_data[lec_str]:
            return self._topics_data[lec_str]["topics"]
        
        return []

    def get_all_topics(self) -> List[str]:
        """
        Returns a flat list of all topic strings across the entire syllabus.
        """
        all_topics = []
        for key in sorted(self._topics_data.keys(), key=lambda x: int(x)):
            if "topics" in self._topics_data[key]:
                all_topics.extend(self._topics_data[key]["topics"])
        return all_topics

    def find_topic_lecture(self, topic_name: str) -> Optional[int]:
        """
        Returns the lecture number for a specific topic name, if found.
        """
        for key, data in self._topics_data.items():
            if topic_name in data.get("topics", []):
                return int(key)
        return None
