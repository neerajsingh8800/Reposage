"""
Hybrid Retrieval Evaluation Module (Phase 6F).
"""

from pathlib import Path
from typing import Any
from ingestion.repo_walker import chunk_repo
from ingestion.hybrid_search import HybridIndex, hybrid_search
from ingestion.embedder import embed_chunks


def run_retrieval_eval(fixtures: dict[str, Path]) -> dict[str, Any]:
    """Evaluate BM25 search, semantic search, RRF fusion, graph boosting, and Recall@K / MRR."""
    results = {
        "category": "Hybrid Retrieval & Ranking",
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

    # Test cases: (repo_key, repo_id, query, expected_hit_substr)
    test_queries = [
        ("python", "eval_py_retrieval", "validate amount positive number", "validate_amount"),
        ("python", "eval_py_retrieval", "PaymentProcessor process transactions", "PaymentProcessor"),
        ("python", "eval_py_retrieval", "checkout complete customer order", "checkout"),
        ("jsts", "eval_jsts_retrieval", "validateAmount errorCode", "validateAmount"),
        ("jsts", "eval_jsts_retrieval", "PaymentService processPayment auditLog", "PaymentService"),
        ("jsts", "eval_jsts_retrieval", "CheckoutButton Pay Now click", "CheckoutButton"),
    ]

    ranks = []
    hits_at_1 = 0
    hits_at_5 = 0

    for repo_key, repo_id, query, expected_target in test_queries:
        repo_path = fixtures[repo_key]
        chunks = chunk_repo(str(repo_path), verbose=False)
        embed_chunks(chunks, repo_id)
        index = HybridIndex(chunks, repo_id, repo_path=str(repo_path))

        hits = hybrid_search(query, repo_id, top_k=5, index=index, repo_path=str(repo_path))
        qualified_names = [h.get("qualified_name", "") for h in hits]

        found_rank = None
        for r_idx, qn in enumerate(qualified_names):
            if expected_target in qn:
                found_rank = r_idx + 1
                break

        if found_rank is not None:
            ranks.append(1.0 / found_rank)
            hits_at_5 += 1
            if found_rank == 1:
                hits_at_1 += 1
            record_check(f"Query '{query}' found target '{expected_target}' (Rank {found_rank})", True)
        else:
            ranks.append(0.0)
            record_check(f"Query '{query}' found target '{expected_target}'", False, f"Hits: {qualified_names}")

    # Test Graph Neighbor Boosting (1-hop boost)
    # Query 'validateAmount' top hit should boost its direct caller 'PaymentService.processPayment'
    jsts_repo = fixtures["jsts"]
    jsts_chunks = chunk_repo(str(jsts_repo), verbose=False)
    jsts_index = HybridIndex(jsts_chunks, "eval_jsts_retrieval", repo_path=str(jsts_repo))
    boosted_hits = hybrid_search("check if amount is valid validateAmount", "eval_jsts_retrieval", top_k=5, index=jsts_index, repo_path=str(jsts_repo))
    boosted_names = [h.get("qualified_name", "") for h in boosted_hits]

    has_neighbor = any("PaymentService.processPayment" in n or "legacyHandler" in n for n in boosted_names)
    record_check("Graph neighbor boosting elevates connected callers/callees", has_neighbor, f"Hits: {boosted_names}")

    mrr = sum(ranks) / len(ranks) if ranks else 0.0
    recall_at_5 = (hits_at_5 / len(test_queries)) * 100 if test_queries else 0.0

    results["metrics"] = {
        "mrr_score": round(mrr, 3),
        "recall_at_5_pct": round(recall_at_5, 2),
        "top_1_accuracy_pct": round((hits_at_1 / len(test_queries)) * 100, 2),
        "total_queries_evaluated": len(test_queries),
    }

    return results
