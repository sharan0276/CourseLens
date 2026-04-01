
import re

def add_sources_footer(text: str) -> str:
    """
    Extracts [filename, Slide N] citations (including multi-slide like [file, Slide 2, Slide 3]),
    splits them into individual entries, replaces inline with [1][2] style numbers,
    and appends a clean 'Sources Used' bibliography with one entry per slide.
    
    Robustness features:
    - Case-insensitive 'slide' matching.
    - Optional file extensions (.pptx, .pdf, etc.).
    - Flexible whitespace handling.
    """
    
    # Match citation groups like [chap03.pptx, Compound Assignment, Slide: 40]
    # or [chap03.pptx, Assignment Statement]
    # It looks for a filename/chapter start, followed by at least one comma-separated detail.
    pattern = r'\[((?:chap\d+|[a-zA-Z0-9_\-\.]+\.(?:pptx|pdf|docx|txt|html|cpp))[ \t]*,[ \t]*[^\[\]]+)\]'

    if not re.search(pattern, text):
        return text

    def _split_citation(raw: str):
        """
        Splits a raw citation string while preserving topic info.
        Input: 'chap03.pptx, Compound Assignment, Slide: 40' -> ['chap03.pptx, Compound Assignment, Slide: 40']
        Input: 'f, Topic, Slide 1, Slide 2' -> ['f, Topic, Slide 1', 'f, Topic, Slide 2']
        """
        parts = [p.strip() for p in re.split(r',\s*', raw.strip())]
        if len(parts) < 2:
            return [raw]
            
        filename = parts[0]
        
        # Identify which parts are 'Slide' parts
        # Now matches 'Slide 40', 'Slide: 40', 'slide 40', etc.
        slide_indices = [i for i, p in enumerate(parts) if re.search(r'[sS]lide\s*:?\s*\d+', p)]
        
        if not slide_indices:
            # If no slide info, treat the whole thing as one specific citation (e.g., [file, topic])
            return [raw]
            
        # The 'prefix' is everything before the first slide mention (e.g., filename + topic)
        prefix = ", ".join(parts[:slide_indices[0]])
        
        # Return one entry for each slide, keeping the prefix
        return [f"{prefix}, {parts[i]}" for i in slide_indices]

    # First pass — collect all individual citations in order of first appearance
    unique_citations = []
    for match in re.finditer(pattern, text):
        raw = match.group(1)
        for ind in _split_citation(raw):
            if ind not in unique_citations:
                unique_citations.append(ind)

    if not unique_citations:
        return text

    # Map each individual citation to its number
    num_map = {src: f"[{i+1}]" for i, src in enumerate(unique_citations)}

    # Second pass — replace each inline citation group with concatenated numbers e.g. [1][2]
    def _replace(m):
        return ''.join(num_map.get(ind, '') for ind in _split_citation(m.group(1)))

    processed_text = re.sub(pattern, _replace, text)

    # Append clean bibliography
    footer = "\n\nSources Used:"
    for i, src in enumerate(unique_citations, 1):
        footer += f"\n[{i}] {src}"

    return processed_text + footer
