import json
import re
from collections import defaultdict
from pathlib import Path


class ChunkBuilder:
    """
    Responsible for building parent and child chunks from the slides.
    Also add navigation links to prev and next slides to fetch relevant nearby slides.
    """

    def __init__(self, pdf_chunk_size = 1000, pdf_chunk_overlap = 200, extract_pdf_title = True):
        self.pdf_chunk_size = pdf_chunk_size
        self.pdf_chunk_overlap = pdf_chunk_overlap
        self.extract_pdf_title = extract_pdf_title

    def build_from_json(self, json_path: str) ->  tuple[list, list]:
        """
        Reads one JSON file to extract details.
        Returns tuple of (parent_chunks, child_chunks)
        """
        with open(json_path, "r") as f:
            data = json.load(f)
        
        source_type = data.get("source_file").split(".")[-1]
        if source_type == "pptx":
            return self._build_pptx_chunks(data)
        elif source_type == "pdf":
            return self._build_pdf_chunks(data)



    def _build_pptx_chunks(self, data: dict) -> tuple[list, list]:
        """
        Builds parent and child chunks from the PPTX data.
        """
        slides = data.get("slides", [])
        source_file = data.get("source_file")
        
        
        child_chunks = self._build_child_chunks(slides)
        child_chunks = self._add_navigation_links(child_chunks)

        lecture_number = child_chunks[0].get("metadata").get("lecture_number")
        parent_chunks = self._build_parent_chunks(slides, lecture_number, source_file)

        return parent_chunks, child_chunks

    def _build_pdf_chunks(self, data: dict) -> tuple[list, list]:
        """
        Builds parent and child chunks from the PDF data.
        Since PDFs are long documents, we map pages to child chunks and group
        them into parent chunks.
        """
        pages = data.get("slides", []) # Note: data structure seems to reuse the "slides" key for PDF pages
        source_file = data.get("source_file")
        
        child_chunks = []
        for page in pages:
            child_chunks.append(self._build_single_pdf_child(page))
            
        child_chunks = self._add_navigation_links(child_chunks)

        # Assuming pages have a lecture_number just like slides; default to 0 if not
        lecture_number = pages[0].get("lecture_number", 0) if pages else 0
        
        # We can reuse _build_parent_chunks if we map page_number to slide_number
        # but let's just create a single parent for the whole PDF for now, or group by title
        title_groups = defaultdict(list)    
        for page in pages:
            title = page.get("title", "Untitled")
            
            # Map page_number to slide_number temporarily so _build_parent_chunks works
            page_mapped = page.copy()
            page_mapped["slide_number"] = page.get("page_number", 0)
            
            title_groups[title].append(page_mapped)
            
        parent_chunks = []
        for title, group_pages in title_groups.items():
            combined_lines = [title]
            for page in group_pages:
                page_text = self._flatten_content(page.get("content", []))
                if page_text:
                    combined_lines.append(page_text)

            combined_text = "\n".join(combined_lines)
            parent_id = f"chap{lecture_number:02d}_{self._clean_text(title)}"
            child_ids = ",".join([f"chap{lecture_number:02d}_page{page['page_number']:02d}" for page in group_pages])
        
            metadata = {
                "source_file": source_file,
                "lecture_number": lecture_number,
                "title": title,
                "source_type": "pdf",
                "chunk_type" : "parent",
                "child_ids": child_ids,
                "page_count": len(group_pages),
            }

            parent_chunks.append({
                "id" : parent_id,
                "text" : combined_text,
                "metadata" : metadata
            })

        return parent_chunks, child_chunks

    def _build_single_pdf_child(self, page: dict) -> dict:
        """
        Builds one child chunk from a PDF page.
        """
        source_file = page.get("source_file")
        page_number = page.get("page_number", 0)
        lecture_number = page.get("lecture_number", 0)
        title = page.get("title", "Untitled")

        flat_text = self._flatten_content(page.get("content", []))
        full_text = f"{title}\n{flat_text}".strip()

        chunk_id = f"chap{lecture_number:02d}_page{page_number:02d}"
        parent_id = f"chap{lecture_number:02d}_{self._clean_text(title)}"

        metadata = {
            "source_file": source_file,
            "lecture_number": lecture_number,
            "page_number": page_number,
            "title": title,
            "source_type": "pdf",
            "chunk_type" : "child",
            "parent_id": parent_id,
            "has_images": len(page.get("images", [])) > 0,
            "prev_slide" : None,
            "next_slide" : None,
        }
        
        return {
            "id" : chunk_id,
            "text" : full_text,
            "metadata" : metadata
        }


    def _build_child_chunks(self, slides: list) -> list:
        """
        Builds child chunks from the slides.
        """
        return [self._build_single_child(slide) for slide in slides]

    
    def _build_single_child(self, slide:dict) -> dict:
        """
        Builds one child chunk from a slide.
        Handles image-only slides seperately.
        """

        source_file = slide.get("source_file")
        slide_number = slide.get("slide_number")
        lecture_number = slide.get("lecture_number")
        title = slide.get("title", "Untitled")
        only_images = slide.get("only_images", False)

        flat_text = self._flatten_content(slide.get("content", []))
        full_text   = f"{title}\n{flat_text}".strip()

        chunk_id = f"chap{lecture_number:02d}_slide{slide_number:02d}"
        parent_id = f"chap{lecture_number:02d}_{self._clean_text(title)}"

        metadata = {
            "source_file": source_file,
            "lecture_number": lecture_number,
            "slide_number": slide_number,
            "title": title,
            "source_type": "pptx",
            "chunk_type" : "child",
            "parent_id": parent_id,
            "only_images": only_images,
            "has_images": len(slide.get("images", [])) > 0,
            "prev_slide" : None,
            "next_slide" : None,
        }

        if only_images:
            metadata["context_strategy"] = "navigate_previous_neighbors"
            full_text = title
        
        return {
            "id" : chunk_id,
            "text" : full_text,
            "metadata" : metadata
        }


    def _build_parent_chunks(self, slides: list, lecture_number: int, source_file: str) -> list:
        """
        Groups slides by title to create one parent chunk per title group.
        """

        title_groups = defaultdict(list)    
        for slide in slides:
            title = slide.get("title", "Untitled")
            title_groups[title].append(slide)
        

        parent_chunks = []
        for title, group_slides in title_groups.items():
            combined_lines = [title]
            for slide in group_slides:
                slide_text = self._flatten_content(slide.get("content", []))
                if slide_text:
                    combined_lines.append(slide_text)

            combined_text = "\n".join(combined_lines)
            parent_id = f"chap{lecture_number:02d}_{self._clean_text(title)}"
            child_ids = ",".join([f"chap{lecture_number:02d}_slide{slide['slide_number']:02d}" for slide in group_slides])
        
            metadata = {
                "source_file": source_file,
                "lecture_number": lecture_number,
                "title": title,
                "source_type": "pptx",
                "chunk_type" : "parent",
                "child_ids": child_ids,
                "slide_count": len(group_slides),
            }

            parent_chunks.append({
                "id" : parent_id,
                "text" : combined_text,
                "metadata" : metadata
            })
        
        return parent_chunks


    def _add_navigation_links(self, child_chunks: list) -> list:
        """
        Adds navigation links (prev_slide, next_slide) to each chunk.
        """
        for i, chunk in enumerate(child_chunks):
            if i > 0:
                chunk["metadata"]["prev_slide"] = child_chunks[i-1]["id"]
            if i < len(child_chunks) - 1:
                chunk["metadata"]["next_slide"] = child_chunks[i+1]["id"]
        return child_chunks

    
    def _flatten_content(self, content_blocks: list, indent: str = "") -> str:
        """ 
        Recursively flatten hierarchical content into readable text.
        Since all content in ppt are finite , we use recursion.
        """

        lines = []
        for block in content_blocks:
            lines.append(f"{indent}{block['text']}")
            if block.get("children"):
                lines.extend((self._flatten_content(block['children'], indent + " ")).splitlines())
 
        return "\n".join(lines)

    
    def _clean_text(self, text: str) -> str:
        """
        Cleans text for use in IDs.
        """
        return re.sub(r'[^a-z0-9_]', '_', text.lower().strip().replace(" ", "_"))[:50]



