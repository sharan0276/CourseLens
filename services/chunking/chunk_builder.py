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
        
        #source_type = data.get("source_file").split(".")[-1]
        slide = data.get("slides", [])
        if not slide:
            return [], []
        
        source_type = slide[0].get("source_type")
        if source_type == "pptx" or source_type == "pdf_slideshow":
            return self._build_pptx_chunks(data)
        elif source_type == "pdf_notes":
            return self._build_pdf_notes_chunks(data)
        
        return self._build_pptx_chunks(data)



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

    def _build_pdf_notes_chunks(self, data: dict) -> tuple[list, list]:
        """
        Builds parent and child chunks from the PDF notes data.
        Uses sectrion number heirartchy instead of title matching to greoup parent and child.
        Example : 2.1.1, 2.1.2 and 2.1.3 will groped as children of 2.1 
        And sectiosn with no child chunks will be classified as standalone child chunks.
        """
        slides = data.get("slides", []) # Note: data structure seems to reuse the "slides" key for PDF pages
        source_file = data.get("source_file")
        
        if not slides:
            return [], []
    
        lecture_number = slides[0].get("lecture_number")

        child_chunks = self._build_pdf_notes_child_chunks(slides, source_file, lecture_number)

        child_chunks = self._add_navigation_links(child_chunks)

        #parent_chunks = self._build_pdf_notes_parent_chunks(slides, lecture_number, source_file)

        return [] , child_chunks
    
    
    def _build_pdf_notes_child_chunks(self, slides: list, source_file: str, lecture_number: int) -> list:
        """
        Builds child chunks from the PDF notes data.
        """
        child_chunks = []

        for slide in slides:
            title = slide.get("title", "Untitled")
            slide_number = slide.get("slide_number", 0)

            flat_text  = self._flatten_content(slide.get("content", []))
            full_text = f"{title}\n{flat_text}".strip()

            chunk_id = (f"pdf_notes-{title}-page{slide_number}-lecture{lecture_number}")

            # get parent section number
            parent_section = self._get_parent_section_number(title)

            # find the parent chunk id given the parent section number
            parent_id = self._find_parent_id(parent_section, slides, lecture_number) if parent_section else None

            metadata = {
                "source_file": source_file,
                "lecture_number": lecture_number,
                "slide_number": slide_number,
                "title": title,
                "source_type": "pdf_notes",
                "chunk_type" : "child",
                "parent_id": parent_id,
                "only_images": slide.get("only_images", False),
                "has_images": len(slide.get("images", [])) > 0,
                "image_filenames": ",".join([img.get("filename", "") for img in slide.get("images", [])]) if slide.get("images") else "",
                "prev_slide" : None,
                "next_slide" : None,
            }

            child_chunks.append({
                "id" : chunk_id,
                "text" : full_text,
                "metadata" : metadata
            })

        return child_chunks

    
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
            "source_type": slide.get("source_type", "pptx"),
            "chunk_type" : "child",
            "parent_id": parent_id,
            "only_images": only_images,
            "has_images": len(slide.get("images", [])) > 0,
            "image_filenames": ",".join([img.get("filename", "") for img in slide.get("images", [])]) if slide.get("images") else "",
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
        Only creates a parent chunk if the group has more than 1 slide.
        """

        title_groups = defaultdict(list)    
        for slide in slides:
            title = slide.get("title", "Untitled")
            title_groups[title].append(slide)
        

        parent_chunks = []
        for title, group_slides in title_groups.items():
            # Skip creating a parent chunk if this title only appears on 1 slide
            if len(group_slides) <= 1:
                continue
                
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
                "source_type": group_slides[0].get("source_type", "pptx") if group_slides else "pptx",
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

    def _get_parent_section_number(self, title:str):
        """
        Derives parent section number from heading title
        Works by removing the last segment of the section number
        """

        parts = title.strip().split()
        if not parts:
            return None
        
        number = parts[0]

        # if title does not have . it definitely must be a parent with section in whole number
        if "." not in number:
            return None
        
        return number.rsplit(".", 1)[0]


    def _find_parent_id(self, parent_number: str, slides: list, lecture_number: int) -> str:
        """
        Finds the chunk id of the parent section given its number.
        Searches slides for a title starting with parent_number.
        Returns formatted parent chunk id string.
        """

        for slide in slides:
            title = slide.get("title", "")
            parts = title.strip().split()
            if parts and parts[0] == parent_number:
                slide_number = slide.get("slide_number", 0)
                return f"pdf_notes-{title}-page{slide_number}-lecture{lecture_number}"      
        
        return None  


