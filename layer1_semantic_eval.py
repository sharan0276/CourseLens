"""
Layer 1 Semantic Baseline — Benchmarking Pure Vector Search
Bypasses RetrievalService to test the raw performance of BGE-M3 embeddings.
Saves to eval/layer1_semantic_results.json
"""

import json
import chromadb
from pathlib import Path
from services.embedding.embedder import Embedder

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_PATH     = "./CourseLens_data/chroma_db"  
COLLECTION_NAME = "course_lens"
EMBED_MODEL     = "BAAI/bge-m3"
TESTSET_PATH    = "eval/testset_raw.json"
RESULTS_PATH    = "eval/layer1_semantic_results.json"
K_VALUES        = [1, 3, 5]
# ─────────────────────────────────────────────────────────────────────────────

def load_testset(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return [e for e in data if e.get("keep", True)]

def retrieve_pure_semantic(collection, embedder, question: str, k: int) -> list[str]:
    """Pure vector search without any boosting or hybrid fusion."""
    q_emb = embedder.embed_query(question)
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=k,
        include=[] 
    )
    return results["ids"][0]

def reciprocal_rank(ranked_ids: list[str], expected_id: str) -> float:
    for rank, cid in enumerate(ranked_ids, start=1):
        if cid == expected_id:
            return 1.0 / rank
    return 0.0

def main():
    Path("eval").mkdir(exist_ok=True)
    testset = load_testset(TESTSET_PATH)

    print("\n── Connecting to ChromaDB (Direct Access) ──")
    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    embedder   = Embedder(model_name=EMBED_MODEL)

    per_k = {k: {"hits": 0, "rr_sum": 0.0} for k in K_VALUES}
    per_entry = []

    print("\n── Running PURE SEMANTIC evaluation ──")
    for entry in testset:
        q   = entry["question"]
        exp = entry["expected_chunk_id"]
        ranked = retrieve_pure_semantic(collection, embedder, q, 5)

        res = {"id": entry["id"], "question": q, "hit@5": int(exp in ranked)}
        for k in K_VALUES:
            top_k = ranked[:k]
            hit = int(exp in top_k)
            rr = reciprocal_rank(top_k, exp)
            per_k[k]["hits"] += hit
            per_k[k]["rr_sum"] += rr
        per_entry.append(res)

    n = len(testset)
    summary = {f"hit_rate@{k}": round(per_k[k]["hits"]/n, 4) for k in K_VALUES}
    summary.update({f"mrr@{k}": round(per_k[k]["rr_sum"]/n, 4) for k in K_VALUES})

    print("\n── PURE SEMANTIC RESULTS ──")
    for k in K_VALUES:
        print(f"  @{k} Hit Rate: {summary[f'hit_rate@{k}']:.2%}  MRR: {summary[f'mrr@{k}']:.4f}")

    with open(RESULTS_PATH, "w") as f:
        json.dump({"summary": summary, "per_entry": per_entry}, f, indent=2)
    print(f"\n[DONE] Saved to {RESULTS_PATH}")

if __name__ == "__main__":
    main()
