"""
Layer 2 Eval — RAGAS Generation Metrics (PURE SEMANTIC BASELINE)
Runs the generative pipeline using pure dense vector search without Hybrid or Title Boosting.
"""

import os
import json
import chromadb
from dotenv import load_dotenv
from pathlib import Path
from services.embedding.embedder import Embedder
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, wait_exponential, stop_after_attempt

# RAGAS 0.2.x imports
from ragas import evaluate
from ragas.run_config import RunConfig
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from datasets import Dataset

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_PATH      = "./CourseLens_data/chroma_db"  
COLLECTION_NAME  = "course_lens"
EMBED_MODEL      = "BAAI/bge-m3"
TESTSET_PATH     = "eval/testset_raw.json"
RESULTS_PATH     = "eval/layer2_semantic_results.json"
load_dotenv()
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL     = "gemini-2.5-flash"
TOP_K            = 5
# ─────────────────────────────────────────────────────────────────────────────


def retrieve_pure_semantic(collection, embedder, question: str, k: int) -> list[str]:
    """Pure vector search returning chunk texts."""
    q_emb = embedder.embed_query(question)
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=k,
        include=["documents"]
    )
    return results["documents"][0]


@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
def generate_answer(question: str, contexts: list[str], llm) -> str:
    context_block = "\n\n".join(contexts)
    prompt = f"""\
You are a C++ tutoring assistant. Answer the student's question using ONLY \
the context below. Be concise and clear (2-4 sentences). Do not add outside information.

Context:
{context_block}

Question: {question}

Answer:"""
    resp = llm.invoke(prompt)
    return resp.content.strip()


def build_ragas_dataset(testset: list[dict], collection, embedder, llm) -> Dataset:
    rows = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    active = [e for e in testset if e.get("keep", True) and e.get("ground_truth")]

    print(f"[INFO] Evaluating {len(active)} entries using PURE SEMANTIC retrieval.")

    def process_entry(entry):
        q  = entry["question"]
        gt = entry["ground_truth"]
        contexts = retrieve_pure_semantic(collection, embedder, q, TOP_K)
        answer   = generate_answer(q, contexts, llm)
        return entry["id"], q, answer, contexts, gt

    processed = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_entry = {executor.submit(process_entry, entry): entry for entry in active}
        for future in as_completed(future_to_entry):
            entry_id, q, answer, contexts, gt = future.result()
            processed += 1
            print(f"  [{processed}/{len(active)}] {entry_id}: {q[:60]}...")
            
            rows["question"].append(q)
            rows["answer"].append(answer)
            rows["contexts"].append(contexts)
            rows["ground_truth"].append(gt)

    return Dataset.from_dict(rows)


def main():
    Path("eval").mkdir(exist_ok=True)

    print("── Loading test set ──")
    with open(TESTSET_PATH) as f:
        testset = json.load(f)

    print("\n── Connecting to ChromaDB (Pure Semantic) ──")
    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    embedder   = Embedder(model_name=EMBED_MODEL)

    print("\n── Setting up Gemini as RAGAS judge ──")
    langchain_llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0,
        safety_settings={
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        }
    )
    langchain_emb = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    ragas_llm = LangchainLLMWrapper(langchain_llm)
    ragas_emb = LangchainEmbeddingsWrapper(langchain_emb)

    metrics = [faithfulness, answer_relevancy, context_recall, context_precision]
    for m in metrics:
        m.llm = ragas_llm
        if hasattr(m, "embeddings"):
            m.embeddings = ragas_emb

    print("\n── Building eval dataset (retrieve + generate) ──")
    dataset = build_ragas_dataset(testset, collection, embedder, langchain_llm)

    print("\n── Running RAGAS evaluation ──")
    rc = RunConfig(max_workers=2, max_retries=10, max_wait=30)
    results = evaluate(dataset, metrics=metrics, run_config=rc)

    print("\n── Results ──")
    df = results.to_pandas()
    score_cols = [c for c in ["question", "user_input", "faithfulness",
                              "answer_relevancy", "context_recall",
                              "context_precision"] if c in df.columns]
    print(df[score_cols].to_string(index=False))

    summary = {
        "faithfulness":       round(float(df["faithfulness"].mean()),       4),
        "answer_relevancy":   round(float(df["answer_relevancy"].mean()),   4),
        "context_recall":     round(float(df["context_recall"].mean()),     4),
        "context_precision":  round(float(df["context_precision"].mean()),  4),
    }
    print("\n── Aggregate scores ──")
    for k, v in summary.items():
        bar = "█" * int(v * 20)
        print(f"  {k:<22} {v:.4f}  {bar}")

    output = {
        "summary": summary,
        "per_entry": df.to_dict(orient="records")
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n[DONE] Full results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
