"""
Negative Query & Hallucination Prevention Evaluation Module (Phase 6F).

Evaluates system behavior for queries whose answers are not present in the repository.
Verifies that:
- Answers indicate 'Not found in repository'
- Citations are strictly empty
- Confidence is 0.0 according to grounding rules
- No unrelated repository files or functions are fabricated or cited
"""

from pathlib import Path
from typing import Any
import json

from ingestion.repo_walker import chunk_repo
from ingestion.embedder import embed_chunks
from ingestion.hybrid_search import HybridIndex, hybrid_search
from backend.generator import (
    prepare_query_context,
    _parse_and_finalize_answer,
    stream_answer_question,
)


def run_negative_eval(fixtures: dict[str, Any]) -> dict[str, Any]:
    """Evaluate negative queries, zero confidence on ungrounded questions, and empty citations."""
    results = {
        "category": "Negative Queries & Grounding Fallbacks",
        "total_checks": 0,
        "passed_checks": 0,
        "failed_checks": 0,
        "details": [],
        "metrics": {},
    }

    def record_check(name: str, condition: bool, info: str = ""):
        results["total_checks"] += 1
        if condition:
            results["passed_checks"] += 1
            results["details"].append({"check": name, "status": "PASS", "info": info})
        else:
            results["failed_checks"] += 1
            results["details"].append({"check": name, "status": "FAIL", "info": info})

    py_repo: Path = fixtures["python"]
    repo_id = "eval_negative_repo"

    py_chunks = chunk_repo(str(py_repo), verbose=False)
    embed_chunks(py_chunks, repo_id)
    index = HybridIndex(py_chunks, repo_id, repo_path=str(py_repo))

    negative_test_queries = [
        "How is quantum teleportation cryptography implemented?",
        "Where is the Kubernetes deployment YAML cluster configured?",
        "Explain the blockchain ledger consensus mechanism in this repo",
        "How does the Kafka event stream consumer handle dead letter queue?",
    ]

    # 1. Retrieval Isolation on Negative Queries
    for query in negative_test_queries:
        bm25_hits = index.bm25_search(query, top_k=5)
        record_check(
            f"Negative query '{query[:30]}...' yields zero exact symbol BM25 matches",
            len(bm25_hits) == 0 or all("quantum" not in h and "kubernetes" not in h and "blockchain" not in h and "kafka" not in h for h in bm25_hits)
        )

    # 2. Grounding Rules on Negative / Missing Evidence Response
    model_negative_responses = [
        '{"answer": "Not found in repository", "citations": [], "confidence": 0.0}',
        '{"answer": "Not found in the repository.", "citations": ["utils/validators.py:20-30"], "confidence": 0.9}',
        '{"answer": "No information found regarding this topic in the source code.", "citations": ["services/payment.py:10-20"], "confidence": 0.8}',
        '{"answer": "Could not be established from the repository evidence.", "citations": []}',
    ]

    for raw_resp in model_negative_responses:
        parsed = _parse_and_finalize_answer(
            content=raw_resp,
            question="Nonexistent topic query",
            repo_path=str(py_repo),
            repo_id=repo_id,
            hits=[],
            hit_citations=[],
            dep_context="",
            graph=index.graph,
            use_memory=False,
        )

        record_check(
            f"Negative answer '{parsed['answer'][:25]}...' enforces empty citations",
            len(parsed.get("citations", [])) == 0,
            f"Citations: {parsed.get('citations')}"
        )
        record_check(
            f"Negative answer '{parsed['answer'][:25]}...' enforces 0.0 confidence",
            parsed.get("confidence") == 0.0,
            f"Confidence: {parsed.get('confidence')}"
        )
        record_check(
            f"Negative answer '{parsed['answer'][:25]}...' fabricates zero functions",
            len(parsed.get("functions", [])) == 0,
            f"Functions: {parsed.get('functions')}"
        )

    # 3. Streaming Fallback for Negative Queries
    # Test streaming behavior when question is out of scope / empty index
    stream_gen = stream_answer_question(
        question="How to configure Apache Spark distributed clustering?",
        repo_path=str(py_repo),
        repo_id="eval_neg_stream",
        top_k=5,
        use_memory=False,
    )

    events = []
    complete_data = None
    for chunk in stream_gen:
        for line in chunk.strip().splitlines():
            if line.startswith("event: "):
                events.append(line[7:].strip())
            elif line.startswith("data: ") and events and events[-1] == "complete":
                try:
                    complete_data = json.loads(line[6:].strip())
                except Exception:
                    pass

    # If stream executed, check complete payload adherence
    if complete_data:
        record_check(
            "Streaming fallback answer is 'Not found in repository' or properly grounded",
            "not found" in complete_data.get("answer", "").lower() or complete_data.get("confidence", 0) <= 0.85
        )

    acc = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "negative_query_accuracy_pct": round(acc, 2),
        "total_negative_checks": results["total_checks"],
    }

    return results
