import fitz  # PyMuPDF


class PDFSlideshowContentExtractor:
    """
    Responsible for extracting structured content from
    landscape PDF pages (slide deck style).
    Detects title via largest font size on page.
    Returns content blocks matching PPTX pipeline format.
    """

    # Code boundary markers - when we see these we stop joining fragments
    # These signal the end of a logical code line or block
    CODE_BOUNDARIES = (";", "{", "}", "//")

    def extract(self, page, prev_title: str = None) -> list:
        """
        Extracts content from a single PDF page.
        Returns list of content blocks with level, text, children.
        Title block is always level 0, body lines are level 1.

        page - PyMuPDF page object
        prev_title - title of the previous slide, used as fallback
                     when this slide has no detectable title
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

        # Step 4a - titleless slide fallback
        # some slides are pure code with no heading, so the largest
        # font ends up being the code itself - we detect this by
        # checking if the title looks like code rather than a heading
        # if so, we inherit the previous slide title so the chunk
        # still has a meaningful label for retrieval and citation
        if self._looks_like_code(title_text) and prev_title:
            # move the "title" spans back into body since they are code
            body_spans = title_spans + body_spans
            title_text = prev_title

        # Step 5 - reassemble fragmented code lines in body spans
        # slideshow PDFs often split code into individual token spans
        # e.g. "int", "main()", "{" are three separate spans
        # we join them back into complete logical lines using
        # code boundary markers as the stopping signal
        reassembled_body = self._reassemble_code_spans(body_spans)

        # Step 6 - build content blocks in PPTX pipeline format
        content = []

        # Title becomes level 0 block with body as children
        if title_text:
            children = [
                {"level": 1, "text": s["text"].strip()}
                for s in reassembled_body
                if s["text"].strip()
            ]
            content.append({
                "level": 0,
                "text": title_text,
                "children": children
            })

        return content

    def _looks_like_code(self, text: str) -> bool:
        """
        Checks if a string looks like code rather than a slide title.
        Used to detect titleless slides where code was picked up as title.
        Looks for common code markers that would never appear in a heading.
        """
        code_markers = ["{", "}", "#include", "<<", ">>", "int main", "return", "//"]
        return any(marker in text for marker in code_markers)

    def _reassemble_code_spans(self, spans: list) -> list:
        """
        Joins fragmented code spans back into complete logical lines.
        Slideshow PDFs split code into individual tokens as separate spans.
        We buffer tokens and flush when we hit a natural code boundary
        such as semicolon, brace, or comment marker.
        Returns a new list of spans with reassembled text.
        """
        reassembled = []
        buffer = ""

        for span in spans:
            text = span["text"].strip()
            if not text:
                continue

            # accumulate tokens into buffer
            buffer = (buffer + " " + text).strip()

            # flush buffer when we hit a natural code boundary
            # semicolon = end of statement, braces = block delimiter
            # // = comment line end
            if text.endswith(";") or text in ["{", "}"] or text.startswith("//"):
                reassembled.append({"text": buffer, "size": span["size"]})
                buffer = ""

        # flush any remaining buffer that didnt end with a boundary
        # this handles the last line of a slide if it has no semicolon
        if buffer:
            reassembled.append({"text": buffer, "size": spans[-1]["size"]})

        return reassembled

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