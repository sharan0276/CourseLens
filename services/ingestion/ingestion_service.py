import os
import glob
import json
import sys 
sys.path.append("/Users/jyothssena/CourseLens")
from services.ingestion.ppt_parser import PPTXParser
from services.ingestion.pdf_parser import PDFParser
from services.ingestion.cleaner import SlideCleaner

class IngestionService:
    """
    Responsible for orchestrating the ingestion process.
    """
    def __init__(self):
        self.pptx_parser = PPTXParser(image_folder_path="CourseLens_data/images")
        self.pdf_parser = PDFParser(image_folder_path="CourseLens_data/images")
        self.slide_cleaner = SlideCleaner()
        os.makedirs("CourseLens_data/processed_data", exist_ok=True)
        os.makedirs("CourseLens_data/images", exist_ok=True)

    def ingest_folder(self, folder_path: str):
        """
        Orchestrates the ingestion process for a folder of PPTX files.
        """

        files_processed = 0
        total_slides = 0
        patterns = {
            "*.pptx": self.pptx_parser,
            "*.pdf": self.pdf_parser
        }
        for pattern, parser in patterns.items():
            print('p',pattern,parser)
            for filepath in glob.glob(os.path.join(folder_path, pattern)):
                print('qqq')
                try:
                    slides = parser.parse(filepath)
                    cleaned_slides = [self.slide_cleaner.clean(slide) for slide in slides]
                    
                    stem = os.path.splitext(os.path.basename(filepath))[0]
                    output_file = os.path.join("CourseLens_data/processed_data", f"{stem}.json")
                    
                    output_data = {
                        "source_file" : os.path.basename(filepath),
                        "total_slides" : len(cleaned_slides),
                        "slides" : [slide.to_dict() for slide in cleaned_slides]
                    }
                    with open(output_file, "w") as f:
                        json.dump(output_data, f, indent=4)
                    files_processed += 1
                    total_slides += len(cleaned_slides)
            
                except Exception as e:
                    print(f"Error processing {filepath}: {str(e)}")

        return {
            "files_processed" : files_processed,
            "total_extractedslides" : total_slides
        }