import os
import glob
import json
from services.ingestion.ppt_parser import PPTXParser
from services.ingestion.cleaner import SlideCleaner

class IngestionService:
    """
    Responsible for orchestrating the ingestion process.
    """
    def __init__(self):
        self.pptx_parser = PPTXParser(image_folder_path="CourseLens_data/images")
        self.slide_cleaner = SlideCleaner()
        os.makedirs("CourseLens_data/processed_data", exist_ok=True)
        os.makedirs("CourseLens_data/images", exist_ok=True)

    def ingest_folder(self, folder_path: str):
        """
        Orchestrates the ingestion process for a folder of PPTX files.
        """

        files_processed = 0
        total_slides = 0

        for filepath in glob.glob(os.path.join(folder_path, "*.pptx")):
            try:
                slides = self.pptx_parser.parse(filepath)
                cleaned_slides = [self.slide_cleaner.clean(slide) for slide in slides]
                output_file = os.path.join("CourseLens_data/processed_data", os.path.basename(filepath).replace(".pptx", ".json"))
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