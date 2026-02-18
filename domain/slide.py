from typing import List, Dict

class Slide:
    """
    Creating Domain Model for Slide - Establishing the structure of slide
    """
    def __init__(self,  slide_number: int, title: str, 
    content: List[Dict], images: List[Dict], source_file : str):
        self.slide_number = slide_number
        self.title = title
        self.content = content
        self.images = images
        self.source_file = source_file

    
    def to_dict(self):
        """
        Converting domain model to JSON serializable format for meta data storage
        """
        return {
            "slide_number": self.slide_number,
            "title": self.title,
            "content": self.content,
            "images": self.images,
            "source_file": self.source_file
        }
        