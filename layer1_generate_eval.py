"""
Layer 1 Eval — Test Set Generator
Pulls chunks from ChromaDB course_slides collection, uses Gemini to generate
a realistic student question per chunk, saves to JSON for human review.
"""

import json
import time
import random
import chromadb
import google.generativeai as genai
from pathlib import Path
import os

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_PATH        = "./CourseLens_data/chroma_db"          # adjust to your ChromaDB path
COLLECTION_NAME    = "course_lens"
GEMINI_MODEL       = "gemini-2.5-flash"
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")# or load from env
N_CHUNKS           = 40                     # how many chunks to sample
OUTPUT_PATH        = "eval/testset_raw.json"
SLEEP_BETWEEN_CALLS = 1.0                   # seconds, avoid rate limits
RANDOM_SEED        = 42
# ─────────────────────────────────────────────────────────────────────────────

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)


def get_chunks_from_chroma(n: int) -> list[dict]:
    """Pull a random sample of n chunks from course_slides."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)

    total = collection.count()
    print(f"[INFO] Collection '{COLLECTION_NAME}' has {total} chunks.")

    # Fetch all, then sample — ChromaDB has no native random sample
    result = collection.get(include=["documents", "metadatas"])

    ids       = result["ids"]
    docs      = result["documents"]
    metadatas = result["metadatas"]

    combined = list(zip(ids, docs, metadatas))

    # Filter out image-only or very short chunks
    combined = [(i, d, m) for i, d, m in combined if d and len(d.strip()) > 60]

    random.seed(RANDOM_SEED)
    sample = random.sample(combined, min(n, len(combined)))
    print(f"[INFO] Sampled {len(sample)} chunks after filtering.")
    return sample


QUESTION_PROMPT = """\
You are helping evaluate a C++ tutoring RAG system for a university course.

Below is a chunk of content from a course slide. Your job is to write ONE realistic \
student question that this chunk directly and specifically answers.

Rules:
- The question must be answerable primarily from THIS chunk alone
- Write it as a student would ask during study — natural, curious, specific
- Do NOT reference slides, lectures, or course materials in the question
- Do NOT ask overly broad questions ("explain everything about X")
- Maximum one sentence

Chunk:
\"\"\"
{chunk}
\"\"\"

Respond with ONLY the question, no preamble, no punctuation at the end beyond a question mark.
"""


def generate_question(chunk_text: str) -> str | None:
    prompt = QUESTION_PROMPT.format(chunk=chunk_text[:1200])  # cap to avoid token waste
    try:
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        print(f"  [WARN] Gemini call failed: {e}")
        return None


def build_testset(chunks: list[tuple]) -> list[dict]:
    testset = []
    for idx, (chunk_id, doc, meta) in enumerate(chunks):
        print(f"  [{idx+1}/{len(chunks)}] Generating question for: {chunk_id}")
        question = generate_question(doc)
        if question is None:
            continue

        entry = {
            "id":               f"q{idx+1:03d}",
            "question":         question,
            "expected_chunk_id": chunk_id,
            "chunk_preview":    doc[:200],   # first 200 chars for quick review
            "metadata":         meta,
            "reviewed":         False,       # flip to True after human review
            "keep":             True,        # set False to exclude from eval
            "notes":            ""           # free-text for reviewer comments
        }
        testset.append(entry)
        time.sleep(SLEEP_BETWEEN_CALLS)

    return testset


def main():
    Path("eval").mkdir(exist_ok=True)

    print("── Step 1: Pulling chunks from ChromaDB ──")
    chunks = get_chunks_from_chroma(N_CHUNKS)

    print("\n── Step 2: Generating questions with Gemini ──")
    testset = build_testset(chunks)

    print(f"\n── Step 3: Saving {len(testset)} entries to {OUTPUT_PATH} ──")
    with open(OUTPUT_PATH, "w") as f:
        json.dump(testset, f, indent=2)

    print(f"[DONE] Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()