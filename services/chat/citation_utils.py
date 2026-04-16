
import re

def add_sources_footer(text: str) -> str:
    """
    Extracts [filename, Slide N] and [SiteName: Title] citations,
    replaces inline with [1][2] style numbers,
    and appends a single clean 'Sources Used' bibliography.

    Also strips any LLM-generated 'Sources Used' or bulleted reference sections
    to prevent duplication and clutter.
    """
    import re

    # ── Step 0: Strip any existing LLM-generated "Sources Used" sections ──────
    # Matches "Sources Used:" or "References:" followed by list items until end or double newline
    text = re.sub(
        r'\n*(?:Sources Used|References):\s*\n(?:\s*[\*\-•]?\s*(?:\[\d+\]\s*)?[^\n]+\n?)+',
        '',
        text
    ).rstrip()

    # ── Step 1: Define specific citation part extractors ──────────────

    def _split_slide_citation(raw: str):
        """
        Split 'chap01.pptx, Slide 2, Slide 3' -> ['chap01.pptx, Slide 2', 'chap01.pptx, Slide 3']
        """
        parts = re.split(r',\s*', raw.strip())
        if not parts: return [raw]
        filename = parts[0].strip()
        slides = [p.strip() for p in parts[1:] if re.match(r'[sS]lide\s*\d+', p.strip(), re.IGNORECASE)]
        return [f"{filename}, {slide}" for slide in slides] if slides else [raw]

    # ── Step 2: Collect all unique citations in order of appearance ─────────
    unique_citations = []  # list of (display_text, citation_type, url)

    for m in re.finditer(r'\[(.*?)\]', text):
        content = m.group(1)
        # Fast filter: does it contain our known signature patterns?
        if not (re.search(r'\.(pptx|pdf|doc|docx),', content) or 'GeeksForGeeks:' in content or 'W3Schools:' in content or 'LearnCpp:' in content):
            continue
            
        parts = [p.strip() for p in content.split(';')]
        for part in parts:
            if re.search(r'\.(pptx|pdf|doc|docx),', part):
                for ind in _split_slide_citation(part):
                    if not any(c[0] == ind for c in unique_citations):
                        unique_citations.append((ind, "slide", None))
            elif re.match(r'^(GeeksForGeeks|W3Schools|LearnCpp):\s*', part):
                # Handle piped format: "Site: Title | URL"
                url = None
                display = part
                if '|' in part:
                    match = re.match(r'^(.*?)\s*\|\s*(http.*)', part)
                    if match:
                        display = match.group(1).strip()
                        url = match.group(2).strip()
                
                if not any(c[0] == display for c in unique_citations):
                    unique_citations.append((display, "web", url))

    if not unique_citations:
        return text

    # Build number map
    num_map = {display: f"[{i+1}]" for i, (display, _, _) in enumerate(unique_citations)}

    # ── Step 3: Replace inline citations seamlessly ──────────────────────────
    def _replace_bracket(m):
        content = m.group(1)
        if not (re.search(r'\.(pptx|pdf|doc|docx),', content) or 'GeeksForGeeks:' in content or 'W3Schools:' in content or 'LearnCpp:' in content):
            return m.group(0)
            
        parts = [p.strip() for p in content.split(';')]
        final_str = ""
        valid_replacement = False
        
        for part in parts:
            if re.search(r'\.(pptx|pdf|doc|docx),', part):
                subs = _split_slide_citation(part)
                final_str += ''.join(num_map.get(s, '') for s in subs)
                valid_replacement = True
            elif re.match(r'^(GeeksForGeeks|W3Schools|LearnCpp):\s*', part):
                # Normalize piped content to find the correct number in num_map
                display = part.split('|')[0].strip() if '|' in part else part.strip()
                final_str += num_map.get(display, '')
                valid_replacement = True
            else:
                final_str += f"[{part}]"
                
        return final_str if valid_replacement else m.group(0)

    processed_text = re.sub(r'\[(.*?)\]', _replace_bracket, text)

    # ── Step 5: Append unified bibliography ──────────────────────────────────
    footer = "\n\n---\n**Sources Used:**"
    for i, (display, type, url) in enumerate(unique_citations, 1):
        if url:
            # If we have a URL, make it a clickable markdown link
            footer += f"\n- [{i}] [{display}]({url})"
        else:
            footer += f"\n- [{i}] {display}"

    return processed_text + footer
