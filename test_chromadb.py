import chromadb
from services.embedding.embedder import Embedder

embedder = Embedder()

client = chromadb.PersistentClient(path="CourseLens_data/chroma_db")
collection = client.get_collection("course_lens")
print(collection.count())

chunks = [{"text": "what is assignment statement"}]
embedded_chunks = embedder.embed_chunks(chunks)
query_embedding = embedded_chunks[0]["embedding"]

# check what a direct query returns

results = collection.query(
    query_embeddings=[query_embedding],
    n_results=5,
    include=["documents", "metadatas", "distances"]
)

for doc, meta, dist in zip(
    results["documents"][0],
    results["metadatas"][0], 
    results["distances"][0]
):
    print(f"ID: {meta.get('chunk_type')} - {meta.get('title')} - Slide {meta.get('slide_number')} -Lecture {meta.get('lecture_number')} - Score: {round(1-dist, 3)}")

# Quick audit — pull 20 chunks and check lecture_number type
results = collection.get(limit=20, include=["metadatas"])
for m in results["metadatas"]:
    val = m.get("lecture_number")
    print(type(val), val)