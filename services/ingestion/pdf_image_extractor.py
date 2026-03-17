# Extracts embedded images from PDF pages and saves them to the images folder.
# Works identically for both slideshow and notes PDFs - shared extractor.
# PyMuPDF gives us image bytes directly - no EMF conversion needed unlike PPTX.

import os
import fitz  # PyMuPDF


class PDFImageExtractor:
    """
    Responsible for extracting embedded images from PDF pages.
    Saves images as PNG files to the images folder.
    Returns list of image metadata dicts matching PPTX pipeline format.
    """

    def __init__(self, image_folder_path: str):
        # Same image folder as PPTX images - keeps everything in one place
        self.image_folder_path = image_folder_path
        os.makedirs(image_folder_path, exist_ok=True)

    def extract(self, page, page_number: int, 
                source_file: str) -> list:
        """
        Extracts all embedded images from a single PDF page.
        Returns list of image dicts with path and metadata.
        
        page        - PyMuPDF page object
        page_number - used for naming the saved image files
        source_file - filename of the PDF e.g. notes3.pdf
        """

        extracted_images = []

        # get_images() returns a list of image references on this page
        # each reference is a tuple - we only need the first value (xref)
        # xref is PyMuPDF's internal identifier for each image object
        image_list = page.get_images(full=True)

        for image_index, image_ref in enumerate(image_list, start=1):

            # xref is the unique identifier PyMuPDF uses to locate
            # the image data inside the PDF file
            xref = image_ref[0]

            # extract_image() returns a dict with:
            # "image" - raw bytes of the image
            # "ext"   - original format e.g. "jpeg", "png"
            # image details are saved in 
            image_data = page.parent.extract_image(xref)
            image_bytes = image_data["image"]
            
            # Build filename matching PPTX naming convention:
            # sourcefilename_page_N_image_N.png
            # strip .pdf extension from source file for clean naming
            base_name = source_file.replace(".pdf", "")
            image_filename = (
                f"{base_name}_page_{page_number}"
                f"_image_{image_index}.png"
            )
            image_path = os.path.join(
                self.image_folder_path, image_filename
            )

            # Only save if image doesnt already exist
            # Prevents reprocessing on repeated ingestion runs
            if not os.path.exists(image_path):
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

            # Append metadata dict matching PPTX image format
            # so downstream pipeline handles it identically
            extracted_images.append({
                "image_path": image_path,
                "page_number": page_number,
                "image_index": image_index,
                "source_file": source_file
            })

        return extracted_images