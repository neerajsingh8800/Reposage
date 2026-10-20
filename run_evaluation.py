"""
RepoSage Phase 6F Unified Evaluation Runner.

Executes all evaluation suites against isolated, deterministic test fixtures.
Produces human-readable console dashboard summaries and machine-readable JSON metrics.
"""

import sys
import os
import json
import argparse
import tempfile
import datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.fixtures import create_all_fixtures
from evaluation.eval_ingestion import run_ingestion_eval
from evaluation.eval_code_intel import run_code_intel_eval
from evaluation.eval_retrieval import run_retrieval_eval
from evaluation.eval_citations import run_citations_eval
from evaluation.eval_negative import run_negative_eval
from evaluation.eval_memory import run_memory_eval
from evaluation.eval_streaming import run_streaming_eval
from evaluation.eval_isolation import run_isolation_eval
from evaluation.eval_cache import run_cache_eval
from backend.generator import invalidate_repo_cache, clear_conversation_memory


def run_all_evaluations(
    live_llm: bool = False,
    output_path: str | Path = "evaluation_results.json",
    verbose: bool = False,
) -> tuple[dict[str, Any], int]:
    """
    Execute all evaluation suites within a temporary isolated fixture sandbox.
    
    Returns (aggregated_report_dict, exit_code).
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_time = datetime.datetime.now()

    suite_results: list[dict[str, Any]] = []

    # Reset any active memory or cache
    invalidate_repo_cache()
    clear_conversation_memory()

    with tempfile.TemporaryDirectory(prefix="reposage_eval_") as tmp_dir:
        fixtures_dir = Path(tmp_dir)
        fixtures = create_all_fixtures(fixtures_dir)

        # 1. Ingestion Evaluation (Deterministic)
        try:
            res_ingestion = run_ingestion_eval(fixtures)
            res_ingestion["type"] = "deterministic"
            suite_results.append(res_ingestion)
        except Exception as e:
            suite_results.append({
                "category": "Repository Ingestion",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Ingestion Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 2. Code Intelligence Evaluation (Deterministic)
        try:
            res_code_intel = run_code_intel_eval(fixtures)
            res_code_intel["type"] = "deterministic"
            suite_results.append(res_code_intel)
        except Exception as e:
            suite_results.append({
                "category": "Code Intelligence & Dependency Graph",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Code Intelligence Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 3. Hybrid Retrieval Evaluation (Deterministic)
        try:
            res_retrieval = run_retrieval_eval(fixtures)
            res_retrieval["type"] = "deterministic"
            suite_results.append(res_retrieval)
        except Exception as e:
            suite_results.append({
                "category": "Hybrid Retrieval & Ranking",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Retrieval Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 4. Grounded Citations Evaluation (Deterministic)
        try:
            res_citations = run_citations_eval(fixtures)
            res_citations["type"] = "deterministic"
            suite_results.append(res_citations)
        except Exception as e:
            suite_results.append({
                "category": "Grounded Citations & Source Attribution",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Citations Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 5. Negative Queries Evaluation (Deterministic)
        try:
            res_negative = run_negative_eval(fixtures)
            res_negative["type"] = "deterministic"
            suite_results.append(res_negative)
        except Exception as e:
            suite_results.append({
                "category": "Negative Queries & Grounding Fallbacks",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Negative Queries Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 6. Conversation Memory Evaluation (Deterministic)
        try:
            res_memory = run_memory_eval(str(fixtures["python"]))
            res_memory["type"] = "deterministic"
            suite_results.append(res_memory)
        except Exception as e:
            suite_results.append({
                "category": "Conversation Memory & Reference Resolution",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Memory Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 7. SSE Streaming Evaluation (Deterministic Mocked + Optional Live LLM)
        try:
            res_streaming = run_streaming_eval(str(fixtures["python"]), live_llm=live_llm)
            res_streaming["type"] = "hybrid_mock_live" if live_llm else "deterministic_mock"
            suite_results.append(res_streaming)
        except Exception as e:
            suite_results.append({
                "category": "SSE Streaming Protocol",
                "type": "deterministic_mock",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Streaming Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 8. Multi-Tenant Isolation Evaluation (Deterministic)
        try:
            res_isolation = run_isolation_eval(fixtures)
            res_isolation["type"] = "deterministic"
            suite_results.append(res_isolation)
        except Exception as e:
            suite_results.append({
                "category": "Repository Isolation & Multi-Tenancy",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Isolation Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

        # 9. LRU Cache & Latency Evaluation (Deterministic)
        try:
            res_cache = run_cache_eval(fixtures)
            res_cache["type"] = "deterministic"
            suite_results.append(res_cache)
        except Exception as e:
            suite_results.append({
                "category": "In-Memory LRU Cache & Latency",
                "type": "deterministic",
                "total_checks": 1,
                "passed_checks": 0,
                "failed_checks": 1,
                "details": [{"check": "Cache Execution", "status": "FAIL", "info": str(e)}],
                "metrics": {},
            })

    # Clean up state
    invalidate_repo_cache()
    clear_conversation_memory()

    # Aggregate counts
    total_checks = sum(s.get("total_checks", 0) for s in suite_results)
    passed_checks = sum(s.get("passed_checks", 0) for s in suite_results)
    failed_checks = sum(s.get("failed_checks", 0) for s in suite_results)
    skipped_checks = sum(s.get("skipped_checks", 0) for s in suite_results)

    overall_status = "PASS" if failed_checks == 0 and total_checks > 0 else "FAIL"
    elapsed_seconds = round((datetime.datetime.now() - start_time).total_seconds(), 2)

    report = {
        "evaluation_name": "RepoSage Phase 6F Evaluation Suite",
        "timestamp_utc": timestamp,
        "elapsed_seconds": elapsed_seconds,
        "overall_status": overall_status,
        "summary": {
            "total_checks": total_checks,
            "passed": passed_checks,
            "failed": failed_checks,
            "skipped": skipped_checks,
            "pass_rate_pct": round((passed_checks / total_checks) * 100, 2) if total_checks else 0.0,
        },
        "live_llm_enabled": live_llm,
        "suites": suite_results,
    }

    # Write machine-readable JSON
    output_file = Path(output_path)
    output_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Print human-readable summary
    print("\nPhase 6F Evaluation")
    print("=" * 35)

    category_display_map = {
        "Repository Ingestion": "Ingestion",
        "Code Intelligence & Dependency Graph": "Code Intelligence",
        "Hybrid Retrieval & Ranking": "Retrieval",
        "Grounded Citations & Source Attribution": "Citations",
        "Negative Queries & Grounding Fallbacks": "Negative Queries",
        "Conversation Memory & Reference Resolution": "Memory",
        "SSE Streaming Protocol": "Streaming",
        "Multi-Tenant Repository Isolation": "Isolation",
        "Repository Isolation & Multi-Tenancy": "Isolation",
        "In-Memory LRU Cache & Latency": "Cache",
    }

    for suite in suite_results:
        cat_raw = suite.get("category", "Unknown")
        cat_name = category_display_map.get(cat_raw, cat_raw)
        suite_failed = suite.get("failed_checks", 0)
        suite_status = "PASS" if suite_failed == 0 and suite.get("total_checks", 0) > 0 else "FAIL"
        print(f"{cat_name:<20} {suite_status}")

        if verbose:
            for detail in suite.get("details", []):
                chk = detail.get("check")
                st = detail.get("status")
                inf = f" ({detail.get('info')})" if detail.get("info") else ""
                print(f"  [{st}] {chk}{inf}")

    print("\n" + "-" * 35)
    print(f"Total:   {total_checks}")
    print(f"Passed:  {passed_checks}")
    print(f"Failed:  {failed_checks}")
    print(f"Skipped: {skipped_checks}")
    print("-" * 35)
    print(f"Overall: {overall_status}")
    print(f"\nReport written to: {output_file.resolve()}\n")

    exit_code = 0 if overall_status == "PASS" else 1
    return report, exit_code


def main():
    parser = argparse.ArgumentParser(description="RepoSage Phase 6F Evaluation Harness")
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="Run optional live LLM evaluations against Groq API (requires GROQ_API_KEY).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="evaluation_results.json",
        help="Path to output JSON evaluation report (default: evaluation_results.json).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose check-by-check details.",
    )

    args = parser.parse_args()
    _, exit_code = run_all_evaluations(
        live_llm=args.live_llm,
        output_path=args.output,
        verbose=args.verbose,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
