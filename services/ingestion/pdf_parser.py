import os
import io
from PyPDF2 import PdfReader
from PIL import Image


class PDFImageExtractor:
    """
    Responsible for extracting images from a PDF page using PyPDF2.
    Note: PyPDF2 image extraction is limited — not all PDF image encodings
    are supported. Consider PyMuPDF for more reliable extraction.
    """
    def __init__(self, image_folder_path: str):
        self.image_folder_path = image_folder_path
        os.makedirs(image_folder_path, exist_ok=True)

    def extract(self, page, page_number: int, source_filename: str) -> list:
        images = []
        base = os.path.splitext(source_filename)[0]

        try:
            for img_index, image_obj in enumerate(page.images, start=1):
                img_filename = f"{base}_page{page_number}_img{img_index}.png"
                img_path = os.path.join(self.image_folder_path, img_filename)

                img = Image.open(io.BytesIO(image_obj.data))
                img.save(img_path)

                images.append({
                    "image_path": img_path,
                    "image_index": img_index
                })
        except Exception as e:
            print(f"  [ImageExtractor] Page {page_number}: {str(e)}")

        return images


class PDFContentExtractor:
    """
    Responsible for extracting and structuring text content from a PDF page.
    PyPDF2 does not preserve layout/hierarchy, so all text is returned
    as a single flat block per page.
    """
    def extract(self, page, page_number: int) -> list:
        raw_text = page.extract_text() or ""
        blocks = []

        for line in raw_text.splitlines():
            line = line.strip()
            if line:
                blocks.append({
                    "level": 1,
                    "text": line,
                    "children": []
                })

        return blocks


class PDFPage:
    """
    Data class representing a single parsed PDF page.
    Mirrors the Slide object used in the PPTX pipeline.
    """
    def __init__(self, page_number: int, title: str, content: list, images: list, source_file: str):
        self.page_number = page_number
        self.title = title
        self.content = content
        self.images = images
        self.source_file = source_file

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "title": self.title,
            "content": self.content,
            "images": self.images,
            "source_file": self.source_file
        }


class PDFParser:
    """
    Responsible for reading PDF files and extracting text and images per page.
    Mirrors PPTXParser in structure and interface.
    """
    def __init__(self, image_folder_path: str):
        self.content_extractor = PDFContentExtractor()
        self.image_extractor = PDFImageExtractor(image_folder_path)

    def parse(self, filepath: str) -> list:
        """
        Parses the PDF file and returns a list of PDFPage objects,
        one per page.
        """
        reader = PdfReader(filepath)
        source_filename = os.path.basename(filepath)
        pages = []

        # Use PDF metadata title as a document-level fallback
        meta_title = None
        if reader.metadata and reader.metadata.title:
            meta_title = reader.metadata.title.strip()

        for page_number, page in enumerate(reader.pages, start=1):
            txt_blocks = self.content_extractor.extract(page, page_number)
            images = self.image_extractor.extract(page, page_number, source_filename)

            # Title strategy: first non-empty text line on the page,
            # fall back to PDF metadata title, then a generic label
            if txt_blocks:
                title = txt_blocks[0]["text"]
            elif meta_title:
                title = f"{meta_title} — Page {page_number}"
            else:
                title = f"Page {page_number}"

            pages.append(PDFPage(
                page_number=page_number,
                title=title,
                content=txt_blocks,
                images=images,
                source_file=source_filename
            ))

        return pages