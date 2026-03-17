from typing import List, Dict

class Slide:
    """
    Creating Domain Model for Slide - Establishing the structure of slide
    """
    def __init__(self,  slide_number: int, title: str, 
    content: List[Dict], images: List[Dict], source_file : str, 
    lecture_number: int, source_type: str, only_images: bool):
        self.slide_number = slide_number
        self.title = title
        self.content = content
        self.images = images
        self.source_file = source_file
        self.lecture_number = lecture_number
        self.source_type = source_type
        self.only_images = only_images

    
    def to_dict(self):
        """
        Converting domain model to JSON serializable format for meta data storage
        """
        return {
            "slide_number": self.slide_number,
            "title": self.title,
            "content": self.content,
            "images": self.images,
            "source_file": self.source_file,
            "lecture_number": self.lecture_number,
            "source_type": self.source_type,
            "only_images": self.only_images
        }
        