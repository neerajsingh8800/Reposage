"""
Ingestion & Parser Evaluation Module (Phase 6F).
"""

from pathlib import Path
from typing import Any
from ingestion.repo_walker import chunk_repo
from ingestion.chunker import chunk_python_file, chunk_js_ts_file


def run_ingestion_eval(fixtures: dict[str, Path]) -> dict[str, Any]:
    """Evaluate repository ingestion, AST parsers, line coordinates, and malformed source handling."""
    results = {
        "category": "Repository Ingestion",
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

    # 1. Python Ingestion
    py_repo = fixtures["python"]
    py_chunks, py_stats = chunk_repo(str(py_repo), verbose=False, return_stats=True)
    record_check("Python files discovered >= 3", py_stats["files_discovered"] >= 3, f"Found {py_stats['files_discovered']}")
    record_check("Python files skipped == 0", py_stats["files_skipped"] == 0, f"Skipped {py_stats['files_skipped']}")
    record_check("Python chunks extracted > 0", len(py_chunks) > 0, f"Extracted {len(py_chunks)} chunks")

    # Check line coordinates and types
    valid_coords = all(c.start_line > 0 and c.end_line >= c.start_line for c in py_chunks)
    record_check("Python chunk line numbers valid", valid_coords)

    py_types = {c.chunk_type for c in py_chunks}
    record_check("Python chunk types include function/class/method", bool({"function", "class", "method"}.intersection(py_types)))

    # 2. JS/TS Ingestion
    jsts_repo = fixtures["jsts"]
    jsts_chunks, jsts_stats = chunk_repo(str(jsts_repo), verbose=False, return_stats=True)
    record_check("JS/TS files discovered >= 4", jsts_stats["files_discovered"] >= 4, f"Found {jsts_stats['files_discovered']}")
    record_check("JS/TS files skipped == 0", jsts_stats["files_skipped"] == 0, f"Skipped {jsts_stats['files_skipped']}")
    
    jsts_names = {c.name for c in jsts_chunks}
    record_check("TS interfaces/enums/types extracted", bool({"ValidationResult", "Currency", "Amount"}.intersection(jsts_names)))
    record_check("TS functions/classes/methods extracted", bool({"validateAmount", "PaymentService", "processPayment"}.intersection(jsts_names)))
    record_check("TSX React component extracted", "CheckoutButton" in jsts_names)
    record_check("CommonJS module function extracted", "legacyHandler" in jsts_names)

    # 3. Mixed Ingestion
    mixed_repo = fixtures["mixed"]
    mixed_chunks, mixed_stats = chunk_repo(str(mixed_repo), verbose=False, return_stats=True)
    record_check("Mixed repo discovered both Python & TS", mixed_stats["files_discovered"] >= 2)
    record_check("Mixed repo zero skipped files", mixed_stats["files_skipped"] == 0)

    # 4. Malformed Ingestion Recovery
    mal_repo = fixtures["malformed"]
    mal_chunks, mal_stats = chunk_repo(str(mal_repo), verbose=False, return_stats=True)
    record_check("Malformed repo does not crash", len(mal_chunks) >= 2, f"Extracted {len(mal_chunks)} chunks")
    mal_names = {c.name for c in mal_chunks}
    record_check("Valid chunks in malformed repo retained", "compute_total" in mal_names and "calculateTax" in mal_names)

    success_rate = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "ingestion_success_rate_pct": round(success_rate, 2),
        "total_chunks_processed": len(py_chunks) + len(jsts_chunks) + len(mixed_chunks) + len(mal_chunks),
    }

    return results
