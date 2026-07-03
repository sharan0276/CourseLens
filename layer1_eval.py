"""
Layer 1 Eval — Hit Rate & MRR
Loads reviewed testset_raw.json, queries ChromaDB for each question,
computes hit rate and MRR at k=1, 3, 5. Saves results to eval/layer1_results.json.
"""

import json
from pathlib import Path
from services.embedding.embedder import Embedder
from services.rag.retrieval_service import RetrievalService
from services.rag.pinecone_retriever import VectorStoreManager
from services.rag.bm25_retriever import BM25Manager

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_PATH     = "./CourseLens_data/chroma_db"  
COLLECTION_NAME = "course_lens"
EMBED_MODEL     = "BAAI/bge-m3"   # must match ingestion-time embedder
TESTSET_PATH    = "eval/testset_raw.json"
RESULTS_PATH    = "eval/layer1_results.json"
K_VALUES        = [1, 3, 5]
# ─────────────────────────────────────────────────────────────────────────────


def load_testset(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    active = [e for e in data if e.get("keep", True)]
    reviewed = [e for e in active if e.get("reviewed", False)]
    print(f"[INFO] Loaded {len(active)} active entries ({len(reviewed)} reviewed).")
    if len(reviewed) < len(active):
        print(f"  [WARN] {len(active) - len(reviewed)} entries not yet reviewed — including anyway.")
    return active


def retrieve(retriever: RetrievalService, question: str, k: int) -> list[str]:
    """Returns list of chunk IDs in ranked order using production Hybrid logic."""
    # disable_swapping=True ensures we test individual slide quality
    docs = retriever.retrieve(question, k=k, disable_swapping=True)
    return [doc.metadata.get("id") or getattr(doc, "id", "unknown") for doc in docs]


def reciprocal_rank(ranked_ids: list[str], expected_id: str) -> float:
    for rank, cid in enumerate(ranked_ids, start=1):
        if cid == expected_id:
            return 1.0 / rank
    return 0.0


def evaluate(testset: list[dict], retriever: RetrievalService) -> dict:
    per_k = {k: {"hits": 0, "rr_sum": 0.0} for k in K_VALUES}
    per_entry = []
    max_k = max(K_VALUES)

    for entry in testset:
        q   = entry["question"]
        exp = entry["expected_chunk_id"]

        ranked = retrieve(retriever, q, max_k)

        entry_result = {
            "id":               entry["id"],
            "question":         q,
            "expected":         exp,
            "retrieved_top5":   ranked,
        }

        for k in K_VALUES:
            top_k = ranked[:k]
            hit   = int(exp in top_k)
            rr    = reciprocal_rank(top_k, exp)
            per_k[k]["hits"]   += hit
            per_k[k]["rr_sum"] += rr
            entry_result[f"hit@{k}"] = hit
            entry_result[f"rr@{k}"]  = round(rr, 4)

        per_entry.append(entry_result)

    n = len(testset)
    summary = {}
    for k in K_VALUES:
        summary[f"hit_rate@{k}"] = round(per_k[k]["hits"]   / n, 4)
        summary[f"mrr@{k}"]      = round(per_k[k]["rr_sum"] / n, 4)

    return {"n": n, "summary": summary, "per_entry": per_entry}


def print_summary(results: dict):
    print("\n── Layer 1 Retrieval Results ──")
    print(f"  Test set size: {results['n']}")
    print()
    for k in K_VALUES:
        hr  = results["summary"][f"hit_rate@{k}"]
        mrr = results["summary"][f"mrr@{k}"]
        bar = "█" * int(hr * 20)
        print(f"  @{k}  Hit Rate: {hr:.2%}  {bar:<20}  MRR: {mrr:.4f}")
    print()

    # Flag failures for inspection
    failures = [e for e in results["per_entry"] if e["hit@5"] == 0]
    if failures:
        print(f"  [!] {len(failures)} questions missed at k=5 — review these:")
        for f in failures[:5]:
            print(f"      {f['id']}: {f['question'][:80]}")
        if len(failures) > 5:
            print(f"      ... and {len(failures)-5} more (see results JSON)")


def main():
    Path("eval").mkdir(exist_ok=True)

    print("── Loading test set ──")
    testset = load_testset(TESTSET_PATH)

    print("\n── Connecting to Production Retrieval Stack ──")
    embedder = Embedder(model_name=EMBED_MODEL)
    vsm = VectorStoreManager(embeddings_model=embedder)
    bm25 = BM25Manager()
    retriever = RetrievalService(vector_store_manager=vsm, bm25_manager=bm25)

    print("\n── Running retrieval eval (Hybrid 90/10 + 1.05x Boost) ──")
    results = evaluate(testset, retriever)

    print_summary(results)

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[DONE] Full results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()