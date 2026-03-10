# Extracts text content from landscape/slideshow PDF pages.
# Uses font size to detect slide titles reliably rather than
# assuming first line is always the title.
# One page = one slide worth of content blocks.

import fitz  # PyMuPDF


class PDFSlideshowContentExtractor:
    """
    Responsible for extracting structured content from
    landscape PDF pages (slide deck style).
    Detects title via largest font size on page.
    Returns content blocks matching PPTX pipeline format.
    """

    def extract(self, page) -> list:
        """
        Extracts content from a single PDF page.
        Returns list of content blocks with level, text, children.
        Title block is always level 0, body lines are level 1.
        
        page - PyMuPDF page object
        """

        # get_text("dict") returns full layout info including font sizes
        # structured as blocks > lines > spans
        # spans are the smallest unit - individual text runs with same formatting
        page_dict = page.get_text("dict")

        # Step 1 - collect all text spans with their font sizes
        # a span is a run of text with consistent formatting
        # e.g. bold title "Functions" is one span, body text is another
        spans = self._extract_spans(page_dict)

        # Nothing on this page - return empty content
        if not spans:
            return []

        # Step 2 - find the largest font size on the page
        # almost certainly the slide title
        max_font_size = max(span["size"] for span in spans)

        # Step 3 - separate title spans from body spans
        # spans within 2pts of max size are considered title
        # the 2pt tolerance handles slight font size variations
        # in exported PDFs where title might be 23.9pt vs 24pt
        title_spans = [
            s for s in spans 
            if abs(s["size"] - max_font_size) <= 2
        ]
        body_spans = [
            s for s in spans 
            if abs(s["size"] - max_font_size) > 2
        ]

        # Step 4 - merge title spans into one clean title string
        # multiple spans can form one title line e.g. 
        # "Function" + " Declaration" + " Syntax" are 3 spans
        title_text = " ".join(
            s["text"].strip() for s in title_spans 
            if s["text"].strip()
        )

        # Step 5 - build content blocks in PPTX pipeline format
        content = []

        # Title becomes level 0 block with body as children
        if title_text:
            children = [
                {"level": 1, "text": s["text"].strip()}
                for s in body_spans
                if s["text"].strip()
            ]
            content.append({
                "level": 0,
                "text": title_text,
                "children": children
            })

        return content

    def _extract_spans(self, page_dict: dict) -> list:
        """
        Flattens PyMuPDF page dict structure into list of spans.
        PyMuPDF nests text as: blocks > lines > spans
        We flatten this to just spans with text and font size.
        Filters out empty spans and whitespace-only spans.
        """
        spans = []

        # blocks are top level groupings of text on the page
        for block in page_dict.get("blocks", []):

            # type 0 is text block, type 1 is image block
            # we only want text blocks here
            if block.get("type") != 0:
                continue

            # lines are rows of text within a block
            for line in block.get("lines", []):

                # spans are individual text runs within a line
                # each span has consistent font size and style
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    size = span.get("size", 0)

                    # skip empty spans and tiny text
                    # tiny text is usually page numbers or footers
                    if text and size > 6:
                        spans.append({
                            "text": text,
                            "size": size
                        })

        return spans