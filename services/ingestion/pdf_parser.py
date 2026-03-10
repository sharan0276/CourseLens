import os
import re
import fitz  # PyMuPDF
from domain.slide import Slide
from services.ingestion.pdf_slide_content_extractor import PDFSlideshowContentExtractor
from services.ingestion.pdf_notes_content_extractor import PDFNotesContentExtractor
from services.ingestion.pdf_image_extractor import PDFImageExtractor

class PDFParser:
    """
    Responsible for reading PDF files and extracting content.
    Detects document type (slideshow or notes) and uses appropriate extractor.
    Returns a list of Slide objects similar to PPTXParser to maintain indentical format.
    """

    def __init__(self, image_folder_path: str):
        self.image_folder_path = image_folder_path
        self.image_extractor = PDFImageExtractor(image_folder_path)


    def _detect_orientation(self, doc) -> str:
        """
        Checks the first page dimensions to determine document type.
        If the width > height it is a slideshow  (16:9 or 4:3)
        Else it will be coinsidered as regular pdf notes document (A4 or Letter)
        """

        first_page = doc[0]
        width = first_page.rect.width
        height = first_page.rect.height

        return "slideshow" if width > height else "notes"
    

    def _extract_lecture_number(self, filepath: str) -> int:
        """
        Extracts lecture number from filename using regex pattern
        """

        match = re.search(r'\d+', os.path.basename(filepath))
        # To ensure that the value does not crash when number is not foudn default setting to 0
        return int(match.group()) if match else 0

    
    def parse_pdf(self, filepath: str):
        """
        Parses the PDF file and returns list of Slide objects.
        Routes to slideshow or notes extrtactor based on orientation.
        """

        doc = fitz.open(filepath)
        source_file = os.path.basename(filepath)
        lec_num =  self._extract_lecture_number(filepath)

        # Detect orientation and instantiate correct extractor
        orientation = self._detect_orientation(doc)

        if orientation == "slideshow":
            slides = self._parse_slideshow(doc, source_file, lec_num)

        else:
            slides = self._parse_notes(doc, source_file, lec_num)

        doc.close()
        return slides

        
    def _parse_slideshow(self, doc, source_file: str, lec_num:int):
        """
        For landscape PDFs — each page is one slide.
        Same logic as PPTXParser page loop.
        """

        extractor = PDFSlideshowContentExtractor()
        slides = []

        for pagenumber, page in enumerate(doc, start = 1):
            content = extractor.extract(page)
            images = self.image_extractor.extract(
                page, pagenumber, source_file
            )
            only_images = len(content) == 0 and len(images) > 0
            title = self._extract_title(content, pagenumber)

            slides.append(Slide(
                slide_number=pagenumber,
                title=title,
                content=content,
                images=images,
                source_file=source_file,
                lecture_number=lec_num,
                source_type="pdf_slideshow",
                only_images=only_images
            ))

        return slides

    def _parse_notes(self, doc, source_file: str, lec_num: int):
        """
        For portrait PDFs — collects all content from pages, and splits by section
        Preseves starting page naumber for each section - citation purpose.
        """
        extractor = PDFNotesContentExtractor()

        # Step 1 - Collect text from ever page with page numbers so as to knwo sections where they start
        pages_text = []
        for page_number, page in enumerate(doc, start = 1):
            text = page.get_text("text").strip()
            if text:
                pages_text.append({
                    "page_number" : page_number,
                    "text" : text
                })

        # Step 2 - Fetch relevant sectios with start page numbers
        sections = extractor.extract(pages_text)


        # Step 3 - Extracting each sections into one slide (one section = one slide)
        # Ensures comprehensive coverage of all relevant content
        slides = []
        for section in sections:
            only_images = (
                len(section["content"]) == 0 and 
                len(section.get("images", [])) > 0               
            )

            slides.append(Slide(
                slide_number = section["start_page"],
                title = section["title"],
                content = section["content"],
                images = [],
                source_file = source_file,
                lecture_number = lec_num,
                source_type = "pdf_notes",
                only_images = only_images
            ))

        return slides

            

    # Helper function to extract the title name for each chunk
    def _extract_title(self, content: list, 
                       page_number: int) -> str:
        """
        Gets title from first content block.
        Used by slideshow path only.
        Notes path gets title from section heading directly.
        """
        if content and content[0].get("text"):
            return content[0]["text"].strip()
        return f"Page {page_number}"


        
