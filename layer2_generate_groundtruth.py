"""
Layer 2 Eval — Ground Truth Generator
Reads testset_raw.json, fetches the full chunk text from ChromaDB,
and asks Gemini to write a reference answer for each question.
Saves ground truth back into the same JSON file.
"""

import json
import time
import chromadb
import google.generativeai as genai
from pathlib import Path
import os

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_PATH        = "./CourseLens_data/chroma_db" 
COLLECTION_NAME    = "course_lens"
GEMINI_MODEL       = "gemini-2.5-flash"
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
TESTSET_PATH       = "eval/testset_raw.json"
SLEEP_BETWEEN_CALLS = 1.0
# ─────────────────────────────────────────────────────────────────────────────

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)


def load_testset(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def save_testset(path: str, data: list[dict]):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def fetch_chunk_texts(chunk_ids: list[str], collection) -> dict[str, str]:
    """Batch-fetch full chunk text from ChromaDB by ID."""
    result = collection.get(ids=chunk_ids, include=["documents"])
    return dict(zip(result["ids"], result["documents"]))


GROUND_TRUTH_PROMPT = """\
You are writing a model answer for a C++ tutoring system.

A student asked the following question:
"{question}"

The authoritative source material that answers this question is:
\"\"\"
{chunk}
\"\"\"

Write a clear, accurate, concise reference answer (2-4 sentences) based ONLY on the \
source material above. Do not add information from outside the source. Write as if \
explaining to a university student learning C++.

Respond with ONLY the answer, no preamble.
"""


def generate_ground_truth(question: str, chunk_text: str) -> str | None:
    prompt = GROUND_TRUTH_PROMPT.format(
        question=question,
        chunk=chunk_text[:1500]
    )
    try:
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        print(f"  [WARN] Gemini call failed: {e}")
        return None


def main():
    print("── Loading test set ──")
    testset = load_testset(TESTSET_PATH)
    active  = [e for e in testset if e.get("keep", True)]

    # Skip entries that already have ground truth
    needs_gt = [e for e in active if not e.get("ground_truth")]
    print(f"[INFO] {len(needs_gt)} entries need ground truth.")

    if not needs_gt:
        print("[INFO] All entries already have ground truth. Nothing to do.")
        return

    print("\n── Fetching chunks from ChromaDB ──")
    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)

    chunk_ids  = [e["expected_chunk_id"] for e in needs_gt]
    chunk_map  = fetch_chunk_texts(chunk_ids, collection)

    print("\n── Generating ground truth answers ──")
    for idx, entry in enumerate(needs_gt):
        cid        = entry["expected_chunk_id"]
        chunk_text = chunk_map.get(cid, "")

        if not chunk_text:
            print(f"  [{idx+1}/{len(needs_gt)}] SKIP {entry['id']} — chunk text not found")
            continue

        print(f"  [{idx+1}/{len(needs_gt)}] {entry['id']}: {entry['question'][:60]}...")
        gt = generate_ground_truth(entry["question"], chunk_text)

        if gt:
            # Write directly into the testset entry (mutates in place)
            entry["ground_truth"] = gt
        else:
            entry["ground_truth"] = None

        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"\n── Saving updated test set to {TESTSET_PATH} ──")
    save_testset(TESTSET_PATH, testset)

    succeeded = sum(1 for e in needs_gt if e.get("ground_truth"))
    print(f"[DONE] Ground truth added for {succeeded}/{len(needs_gt)} entries.")


if __name__ == "__main__":
    main()