import json
import glob

for json_path in glob.glob("CourseLens_data/processed_data/*.json"):
    with open(json_path) as f:
        data = json.load(f)
    
    empty = []
    for slide in data["slides"]:
        title = slide.get("title", "")
        content = slide.get("content", [])
        if not title and not content:
            empty.append(slide.get("slide_number"))
    
    print(f"{data['source_file']}: {len(data['slides'])} slides, {len(empty)} empty")


with open("CourseLens_data/processed_data/Notes3.json") as f:
    data = json.load(f)

slides = data['slides'][:3]

for slide in slides:
    print(f"The format for slide ", slide['source_type'])
    print(f"Slide Number ", slide['slide_number'])
    


