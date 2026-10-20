"""
Multi-Repository Isolation Evaluation Module (Phase 6F).
"""

from pathlib import Path
from typing import Any
from ingestion.repo_walker import chunk_repo
from ingestion.embedder import embed_chunks
from ingestion.graph_builder import build_graph, callers_of
from ingestion.hybrid_search import HybridIndex, hybrid_search
from backend.generator import (
    add_conversation_turn,
    get_conversation_history,
    clear_conversation_memory,
    get_cached_repo_analysis,
    set_cached_repo_analysis,
    invalidate_repo_cache,
)


def run_isolation_eval(fixtures: dict[str, Path]) -> dict[str, Any]:
    """Evaluate multi-tenant repository isolation across graphs, retrieval, caches, and conversation memory."""
    results = {
        "category": "Repository Isolation & Multi-Tenancy",
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

    repo_a = fixtures["tenant_a"]
    repo_b = fixtures["tenant_b"]

    chunks_a = chunk_repo(str(repo_a), verbose=False)
    chunks_b = chunk_repo(str(repo_b), verbose=False)

    embed_chunks(chunks_a, "tenant_a")
    embed_chunks(chunks_b, "tenant_b")

    index_a = HybridIndex(chunks_a, "tenant_a", repo_path=str(repo_a))
    index_b = HybridIndex(chunks_b, "tenant_b", repo_path=str(repo_b))

    # 1. Graph Isolation Check
    graph_a = build_graph(chunks_a, repo_path=str(repo_a))
    graph_b = build_graph(chunks_b, repo_path=str(repo_b))

    callers_a = callers_of(graph_a, "calculate_fee")
    callers_b = callers_of(graph_b, "calculate_fee")

    record_check("Tenant A graph contains dispatch_invoice", any("dispatch_invoice" in c for c in callers_a))
    record_check("Tenant A graph does NOT leak generate_report", not any("generate_report" in c for c in callers_a))
    record_check("Tenant B graph contains generate_report", any("generate_report" in c for c in callers_b))
    record_check("Tenant B graph does NOT leak dispatch_invoice", not any("dispatch_invoice" in c for c in callers_b))

    # 2. Retrieval Isolation Check
    hits_a = hybrid_search("calculate fee 5 percent flat", "tenant_a", top_k=5, index=index_a, repo_path=str(repo_a))
    hits_b = hybrid_search("calculate fee 20 percent enterprise tier", "tenant_b", top_k=5, index=index_b, repo_path=str(repo_b))

    record_check("Tenant A search results exclusively belong to Tenant A", all("tenant_alpha" in h.get("file_path", "") or "billing.py" in h.get("file_path", "") for h in hits_a))
    record_check("Tenant B search results exclusively belong to Tenant B", all("tenant_beta" in h.get("file_path", "") or "billing.py" in h.get("file_path", "") for h in hits_b))

    # 3. Conversation Memory Isolation Check
    clear_conversation_memory("tenant_a")
    clear_conversation_memory("tenant_b")

    add_conversation_turn(
        repo_id="tenant_a",
        question="How does billing work?",
        answer="Tenant A charges a 5% fee via dispatch_invoice.",
        functions=["calculate_fee", "dispatch_invoice"],
        citations=["billing.py:1-5"],
    )

    mem_a = get_conversation_history("tenant_a")
    mem_b = get_conversation_history("tenant_b")

    record_check("Tenant A conversation memory holds 1 turn", len(mem_a) == 1)
    record_check("Tenant B conversation memory is empty (zero contamination)", len(mem_b) == 0)

    # 4. Cache Isolation Check
    set_cached_repo_analysis("tenant_a", str(repo_a), chunks_a, index_a)
    set_cached_repo_analysis("tenant_b", str(repo_b), chunks_b, index_b)

    cached_a = get_cached_repo_analysis("tenant_a", str(repo_a))
    cached_b = get_cached_repo_analysis("tenant_b", str(repo_b))

    record_check("Cached Tenant A analysis retrieved cleanly", cached_a is not None and cached_a.repo_id == "tenant_a")
    record_check("Cached Tenant B analysis retrieved cleanly", cached_b is not None and cached_b.repo_id == "tenant_b")

    invalidate_repo_cache("tenant_a")
    record_check("Invalidation of Tenant A does not invalidate Tenant B", get_cached_repo_analysis("tenant_a", str(repo_a)) is None and get_cached_repo_analysis("tenant_b", str(repo_b)) is not None)

    # Clean up
    invalidate_repo_cache("tenant_b")
    clear_conversation_memory("tenant_a")
    clear_conversation_memory("tenant_b")

    isolation_rate = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "isolation_integrity_pct": round(isolation_rate, 2),
        "cross_tenant_leakage_detected": 0 if results["failed_checks"] == 0 else results["failed_checks"],
    }

    return results
