"""
Cache & Performance Evaluation Module (Phase 6F).
"""

import time
from pathlib import Path
from typing import Any
from ingestion.repo_walker import chunk_repo
from ingestion.hybrid_search import HybridIndex
from backend.generator import (
    get_cached_repo_analysis,
    set_cached_repo_analysis,
    invalidate_repo_cache,
    _analysis_cache,
)


def run_cache_eval(fixtures: dict[str, Path]) -> dict[str, Any]:
    """Evaluate LRU cache hit/miss semantics, invalidation, and warm lookup speed."""
    results = {
        "category": "In-Memory LRU Cache & Latency",
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

    py_repo = fixtures["python"]
    repo_id = "eval_cache_repo"

    invalidate_repo_cache(repo_id)

    # 1. Cache Miss Verification
    miss_entry = get_cached_repo_analysis(repo_id, str(py_repo))
    record_check("Initial lookup is a cache miss", miss_entry is None)

    # 2. Cold Analysis & Storage
    t0 = time.perf_counter()
    chunks = chunk_repo(str(py_repo), verbose=False)
    index = HybridIndex(chunks, repo_id, repo_path=str(py_repo))
    set_cached_repo_analysis(repo_id, str(py_repo), chunks, index)
    cold_time_ms = (time.perf_counter() - t0) * 1000

    # 3. Cache Hit Verification
    t0 = time.perf_counter()
    hit_entry = get_cached_repo_analysis(repo_id, str(py_repo))
    warm_lookup_ms = (time.perf_counter() - t0) * 1000

    record_check("Subsequent lookup is a cache hit", hit_entry is not None)
    record_check("Cache hit latency < 5 ms", warm_lookup_ms < 5.0, f"Latency: {warm_lookup_ms:.3f} ms")

    # 4. Invalidation Verification
    invalidate_repo_cache(repo_id)
    invalidated_entry = get_cached_repo_analysis(repo_id, str(py_repo))
    record_check("Cache invalidation removes repository analysis", invalidated_entry is None)

    results["metrics"] = {
        "cold_build_time_ms": round(cold_time_ms, 2),
        "warm_cache_lookup_time_ms": round(warm_lookup_ms, 4),
        "cache_speedup_factor": round(cold_time_ms / max(0.001, warm_lookup_ms), 1),
    }

    return results
