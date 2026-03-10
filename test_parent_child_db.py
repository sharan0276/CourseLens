import chromadb

client = chromadb.PersistentClient(path="CourseLens_data/chroma_db")
collection = client.get_collection("course_lens")

all_metas = collection.get(include=["metadatas"])

parent_metas = [meta for meta in all_metas['metadatas'] if meta['chunk_type'] == 'parent']
child_metas = [meta for meta in all_metas['metadatas'] if meta['chunk_type'] == 'child']

print(f"Parent: {len(parent_metas)}")
print(f"Child: {len(child_metas)}")

from collections import Counter

parent_ids = [m['parent_id'] for m in child_metas if m.get('parent_id')]
count = Counter(parent_ids)
solo_parents = [pid for pid, counts in count.items() if counts == 1]
print(f"Solo Parents: {len(solo_parents)}")


for chunk_id, metadata in zip(all_metas['ids'], all_metas['metadatas']):
    if metadata['chunk_type'] == 'parent' and chunk_id in solo_parents and metadata['lecture_number'] == 1:
        print(f"Title: {metadata['title']} | Lecture: {metadata['lecture_number']} | child_id: {metadata['child_ids']}")
