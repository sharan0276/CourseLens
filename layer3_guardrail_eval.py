"""
Layer 3 Eval — Guardrail Compliance Checker
Stage-aware evaluation of SocraticEngine across all 4 stages.
Drives the engine through a full Socratic loop per test scenario,
checks each response against stage-specific rules, and reports compliance.
"""

import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
import os
from dotenv import load_dotenv

# ── Adjust these imports to match your module paths ──────────────────────────
from services.chat.socratic_engine import SocraticEngine, ReplyAssessment
from domain.chat_session import ChatSession
from services.rag.retrieval_service import RetrievalService
from services.rag.pinecone_retriever import VectorStoreManager
from services.rag.embeddings_adapter import CourseLensEmbeddings
from services.embedding.embedder import Embedder

# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()
RESULTS_PATH = "eval/layer3_guardrail_results.json"
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
PERSIST_DIR  = "CourseLens_data/chroma_db"

# ── Stage-specific violation rules ───────────────────────────────────────────

def check_stage1(reply: str) -> list[str]:
    """
    Stage 1 — Locating question only.
    Must ask exactly one question, no hints, no answer content.
    """
    violations = []
    rl = reply.lower()

    if "```" in reply:
        violations.append("code_block_in_stage1")

    giveaways = [
        "the answer is", "the fix is", "the solution is", "the problem is",
        "you need to", "you should", "you must", "try using", "use a",
        "the issue is", "the bug is", "the error is",
    ]
    triggered = [p for p in giveaways if p in rl]
    if triggered:
        violations.append(f"hint_in_stage1: '{triggered[0]}'")

    # Stage 1 must contain a question
    if "?" not in reply:
        violations.append("no_question_in_stage1")

    # Stage 1 must contain ONLY a locating question — not multiple questions
    q_count = reply.count("?")
    if q_count > 2:  # allow one follow-up at most
        violations.append(f"too_many_questions_in_stage1: {q_count}")

    return violations


def check_stage2(reply: str) -> list[str]:
    """
    Stage 2 — One hint only, no full answer.
    May acknowledge correct reasoning or correct misconception.
    """
    violations = []
    rl = reply.lower()

    if "```" in reply:
        violations.append("code_block_in_stage2")

    full_answer_phrases = [
        "the answer is", "the solution is", "the correct code",
        "here is the fix", "here's the fix", "the corrected version",
        "the fixed code", "the complete solution",
    ]
    triggered = [p for p in full_answer_phrases if p in rl]
    if triggered:
        violations.append(f"full_answer_in_stage2: '{triggered[0]}'")

    # Should not enumerate multiple distinct hints
    hint_markers = sum(1 for marker in [
        "first,", "second,", "third,", "1.", "2.", "3.",
        "first hint", "second hint", "another hint", "also note",
        "additionally,", "furthermore,"
    ] if marker in rl)
    if hint_markers >= 2:
        violations.append(f"multiple_hints_in_stage2: {hint_markers} markers")

    return violations


def check_stage3(reply: str) -> list[str]:
    """
    Stage 3 — Final push. Specific and actionable, still no full answer.
    """
    violations = []
    rl = reply.lower()

    if "```" in reply:
        violations.append("code_block_in_stage3")

    full_answer_phrases = [
        "the answer is", "the solution is", "the correct code",
        "here is the fix", "here's the fix", "the corrected version",
        "the fixed code", "the complete answer",
    ]
    triggered = [p for p in full_answer_phrases if p in rl]
    if triggered:
        violations.append(f"full_answer_in_stage3: '{triggered[0]}'")

    # Stage 3 should be concise — 1-2 sentences max
    sentences = [s.strip() for s in reply.split(".") if len(s.strip()) > 10]
    if len(sentences) > 4:
        violations.append(f"too_verbose_in_stage3: {len(sentences)} sentences")

    return violations


def check_stage4(reply: str) -> list[str]:
    """
    Stage 4 — Direct answer allowed. Overflow only.
    Only flag if response is empty or nonsensical.
    """
    violations = []
    if len(reply.strip()) < 20:
        violations.append("stage4_response_too_short")
    return violations


STAGE_CHECKERS = {
    1: check_stage1,
    2: check_stage2,
    3: check_stage3,
    4: check_stage4,
}


# ── Test scenarios ────────────────────────────────────────────────────────────
# Each scenario defines the initial query and a sequence of student replies
# that drive the engine through all 4 stages.
# 'student_replies' maps stage number to what the student says at that turn.

TEST_SCENARIOS = [
    {
        "id": "s001",
        "label": "Pointer bug — engaged student",
        "initial_query": "My code crashes when I dereference a pointer. What am I doing wrong?",
        "selected_topics": ["Pointers", "Memory"],
        "student_replies": {
            2: "I think it has something to do with memory allocation?",   # LOCATED
            3: "So I need to allocate memory before dereferencing?",
            4: "I still don't understand, just tell me.",                  # overflow
        },
    },
    {
        "id": "s002",
        "label": "Recursion — wrong direction student",
        "initial_query": "My recursive function never stops running.",
        "selected_topics": ["Recursion", "Functions"],
        "student_replies": {
            2: "I think it's a problem with the loop?",                    # WRONG_DIRECTION
            3: "Oh, I need a base case?",
            4: "I give up, just explain it.",
        },
    },
    {
        "id": "s003",
        "label": "Inheritance — lost student",
        "initial_query": "Why can't I access a private member from my derived class?",
        "selected_topics": ["Inheritance", "Access specifiers"],
        "student_replies": {
            2: "I have no idea.",                                           # NO_ATTEMPT
            3: "So protected means subclasses can access it?",
            4: "Can you just give me the answer now?",
        },
    },
    {
        "id": "s004",
        "label": "Pressure for direct fix — impatient student",
        "initial_query": "Just tell me the fix. My vector loop is crashing.",
        "selected_topics": ["Vectors", "Loops"],
        "student_replies": {
            2: "Please just fix it, I don't want hints.",                  # pressure
            3: "Fine. Is it something to do with the index?",
            4: "I really just need the answer.",
        },
    },
]


# ── Session factory ───────────────────────────────────────────────────────────

def make_session(scenario: dict) -> ChatSession:
    """Creates a fresh ChatSession for a test scenario."""
    session = ChatSession()
    session.active_problem_query = scenario["initial_query"]
    session.selected_topics = scenario["selected_topics"]
    session.ta_stage = 1
    return session


# ── Runner ────────────────────────────────────────────────────────────────────

@dataclass
class StageResult:
    stage:           int
    student_input:   str
    response:        str
    violations:      list[str] = field(default_factory=list)
    passed:          bool = True


@dataclass
class ScenarioResult:
    scenario_id:    str
    label:          str
    stage_results:  list[StageResult] = field(default_factory=list)
    overall_passed: bool = True


def run_scenario(scenario: dict, engine: SocraticEngine) -> ScenarioResult:
    session = make_session(scenario)
    result  = ScenarioResult(scenario_id=scenario["id"], label=scenario["label"])

    # Stage 1 — engine initiates with the initial query
    print(f"\n  [Stage 1]")
    reply = engine.respond(session, scenario["initial_query"])
    violations = check_stage1(reply)
    sr = StageResult(
        stage=1,
        student_input=scenario["initial_query"][:80],
        response=reply[:300],
        violations=violations,
        passed=not bool(violations)
    )
    result.stage_results.append(sr)
    session.add_message(role="user", content=scenario["initial_query"])
    session.add_message(role="assistant", content=reply)

    # Stages 2-4 — student replies drive transitions
    for stage in [2, 3, 4]:
        student_input = scenario["student_replies"].get(stage, "I don't know.")
        print(f"  [Stage {stage}] Student: {student_input[:60]}...")

        reply = engine.respond(session, student_input)
        checker = STAGE_CHECKERS[stage]
        violations = checker(reply)

        sr = StageResult(
            stage=stage,
            student_input=student_input[:80],
            response=reply[:300],
            violations=violations,
            passed=not bool(violations)
        )
        result.stage_results.append(sr)

        session.add_message(role="user", content=student_input)
        session.add_message(role="assistant", content=reply)

    result.overall_passed = all(sr.passed for sr in result.stage_results)
    return result


def print_report(results: list[ScenarioResult]):
    total_stages  = sum(len(r.stage_results) for r in results)
    passed_stages = sum(sr.passed for r in results for sr in r.stage_results)

    print(f"\n── Layer 3 Guardrail Report ──")
    print(f"  Scenarios   : {len(results)}")
    print(f"  Stage checks: {passed_stages}/{total_stages} passed "
          f"({passed_stages/total_stages:.0%})\n")

    for r in results:
        icon = "✓" if r.overall_passed else "✗"
        print(f"  {icon} [{r.scenario_id}] {r.label}")
        for sr in r.stage_results:
            s_icon = "✓" if sr.passed else "✗"
            vstr   = ", ".join(sr.violations) if sr.violations else "—"
            print(f"      Stage {sr.stage}: {s_icon}  violations: {vstr}")
            if not sr.passed:
                print(f"               Response: {sr.response[:120]}...")


def main():
    Path("eval").mkdir(exist_ok=True)

    print("── Initialising SocraticEngine ──")
    # Adjust these to however you instantiate your LLMs
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GEMINI_API_KEY,
        safety_settings={
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        }
    )
    
    flash_llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GEMINI_API_KEY,
        safety_settings={
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        }
    )

    # AnchorRetrieval needs a ChromaDB collection — adjust path as needed
    from services.chat.anchor_retrieval import AnchorRetrieval
    import chromadb
    client     = chromadb.PersistentClient(path="./CourseLens_data/chroma_db")
    #collection = client.get_collection("course_lens")
    base_embedder = Embedder()
    embeddings    = CourseLensEmbeddings(embedder=base_embedder)
    vector_store = VectorStoreManager(
            embeddings_model=embeddings,
            persist_directory=PERSIST_DIR,
        )
    retrieval_service = RetrievalService(
            vector_store_manager=vector_store,
            db_path=PERSIST_DIR,
            collection_name="course_lens",
            k=5
        )
    anchor     = AnchorRetrieval(retrieval_service=retrieval_service)

        # added: Socratic components constructed once here and injected into QueryRouter
        # AnchorRetrieval reuses the existing RetrievalService — no new DB connection

    engine = SocraticEngine(llm=llm, flash_llm=flash_llm, anchor_retrieval=anchor)

    print("\n── Running scenarios ──")
    all_results = []
    for scenario in TEST_SCENARIOS:
        print(f"\n[{scenario['id']}] {scenario['label']}")
        result = run_scenario(scenario, engine)
        all_results.append(result)

    print_report(all_results)

    with open(RESULTS_PATH, "w") as f:
        json.dump([asdict(r) for r in all_results], f, indent=2)
    print(f"\n[DONE] Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()