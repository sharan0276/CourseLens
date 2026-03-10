class SlideCleaner:
    """
    Responsible for cleaning and normalizing slide data.
    """

    def clean(self, slide):
        """
        Performs a secondary sanitary check on teh extracted text blocks.
        To ensure no duplicate text blocks are present.

        Cleans Slide object : 
            - Strips whitespace for parent and child text
            - Removes duplicate texts
        
        """
        seen = set()
        cleaned_blocks = []

        for block in slide.content:
            text = block["text"].strip()

            if not text or text in seen:
                continue

            seen.add(text)

            cleaned_children = []
            for child in block.get('children', []):
                child_text = child['text'].strip()
                if child_text and child_text not in seen:
                    seen.add(child_text)
                    cleaned_children.append({
                        "level": child["level"],
                        "text": child_text
                    })
            
            cleaned_blocks.append({
                "level": block["level"],
                "text": text,
                "children": cleaned_children
            })
        
        slide.content = cleaned_blocks
        return slide