# Extracts structured content from portrait/notes PDF documents.
# Detects numbered section headings (1, 2.1, 2.1.1 pattern) as boundaries.
# Splits full document text into sections - one section = one Slide object.
# Preserves starting page number per section for accurate slide citations.


import re
from typing import List, Dict

class PDFNotesContentExtractor:
    """
    Responsible for extracting structured content from
    portrait PDF documents (lecture notes style).
    Detects numbered headings and builds section hierarchy.
    Returns sections with start page and content blocks.
    """

    # Matches: 1, 2.1, 2.1.1 followed by space and capital letter
    # Correctly identifies academic section headings
    # Rejects normal sentences that happen to start with numbers
    HEADING_PATTERN = re.compile(r'^\d+(\.\d+)*\s+[A-Z]')

    def extract(self, pages_text: List[Dict]) -> List[Dict]:
        """
        Entry point for notes extraction.
        Receives list of {page_number, text} dicts - one per PDF page.
        Returns list of section dicts ready for Slide creation.
        
        pages_text - output from _parse_notes page collection loop
        """

        # Step 1 - flatten pages into individual lines
        # keeps page_number attached to every line for citation tracking
        lines = self._flatten_pages(pages_text)

        # Step 2 - walk through lines and split at heading boundaries
        # everything between two headings belongs to the same section
        sections = self._split_into_sections(lines)

        # Step 3 - convert raw sections into content block format
        # matching the structure PPTXParser and ChunkBuilder expect
        return [self._build_section(section) for section in sections]

    def _flatten_pages(self, pages_text: List[Dict]) -> List[Dict]:
        """
        Converts page level text into individual lines.
        Attaches page_number to every line so we never lose
        which page a section started on.
        If a section number (e.g. "1.1") is on a separate line from its 
        title (e.g. "Compiled Languages"), we gracefully merge them.
        """
        raw_lines = []
        for page in pages_text:
            page_number = page["page_number"]
            for line in page["text"].splitlines():
                line = line.strip()
                # skip empty lines - just whitespace separators
                if line:
                    raw_lines.append({
                        "page_number": page_number,
                        "text": line
                    })

        # Process the raw lines and fix broken headers
        lines = []
        i = 0
        while i < len(raw_lines):
            current_line = raw_lines[i]
            text = current_line["text"]
            
            # Check if this line is EXACTLY a standalone section number (e.g. "1", "2.1")
            is_lone_number = bool(re.match(r'^\d+(\.\d+)*$', text))
            
            # If it is a lone number, and there is a next line...
            if is_lone_number and i + 1 < len(raw_lines):
                next_text = raw_lines[i+1]["text"]
                # ...and the next line starts with a Capital letter (matches a title)
                if re.match(r'^[A-Z]', next_text):
                    # Merge them together! "1.1" + " Why Use C++?"
                    lines.append({
                        "page_number": current_line["page_number"],
                        "text": f"{text} {next_text}"
                    })
                    i += 2  # Skip the next line since we just merged it
                    continue
            
            # Otherwise, just append the line normally
            lines.append(current_line)
            i += 1
            
        return lines

    def _split_into_sections(self, lines: List[Dict]) -> List[Dict]:
        """
        Walks through all lines and starts a new section
        every time a numbered heading is detected.
        Lines before the first heading are skipped -
        these are document headers, author names, dates etc.
        Classic boundary detection pattern - save previous
        section when next heading is found.
        """
        sections = []
        current_section = None

        for line in lines:
            text = line["text"]
            page_number = line["page_number"]

            if self._is_heading(text):
                # save completed section before starting new one
                # this is the boundary detection moment
                if current_section:
                    sections.append(current_section)

                # start fresh section at this heading
                current_section = {
                    "title": text,
                    "start_page": page_number,
                    "level": self._get_heading_level(text),
                    "body_lines": []
                }
            else:
                # regular body paragraph - belongs to current section
                if current_section:
                    current_section["body_lines"].append(text)
                # if no section started yet skip the line
                # handles document title, course number etc.

        # save the last section - loop ends before it gets saved
        # because there is no heading after it to trigger the save
        if current_section:
            sections.append(current_section)

        return sections

    def _is_heading(self, text: str) -> bool:
        """
        Returns True if line matches numbered heading pattern.
        e.g. "2.1 Conditionals" matches, "2 items found" does not
        because it doesnt start with a capital letter after the number.
        """
        return bool(self.HEADING_PATTERN.match(text))

    def _get_heading_level(self, text: str) -> int:
        """
        Derives heading level from dot count in heading number.
        "1 Motivation"     - 0 dots - level 0 (top level)
        "2.1 Conditionals" - 1 dot  - level 1 (subsection)
        "2.1.1 Operators"  - 2 dots - level 2 (sub-subsection)
        Level determines parent-child relationships in ChunkBuilder.
        """
        # first word is always the section number e.g. "2.1.1"
        number_part = text.split()[0]
        return number_part.count(".")

    def _build_section(self, section: Dict) -> Dict:
        """
        Converts raw section into flat content blocks.
        One heading = one Slide with level in metadata.
        ChunkBuilder handles grouping - same as PPTX pattern.
        Level metadata tells ChunkBuilder where this section
        sits in the hierarchy so it can group correctly.
        e.g. level 1 sections belong to nearest level 0 parent.
        """

        heading_level = section["level"]

        # body paragraphs are children of this heading
        # level is heading + 1 same as before
        children = [
            {
                "level": heading_level + 1,
                "text": line
            }
            for line in section["body_lines"]
            if line.strip()
        ]

        # one flat content block per section
        # no nesting - ChunkBuilder decides relationships
        content = [
            {
                "level": heading_level,
                "text": section["title"],
                "children": children
            }
        ]

        return {
            "title": section["title"],
            "start_page": section["start_page"],
            "level": heading_level,     
            "content": content
        }