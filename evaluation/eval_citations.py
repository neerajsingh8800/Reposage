"""
Grounded Citation Evaluation Module (Phase 6F).

Evaluates strict citation grounding, file-level accuracy, line-range validity,
overlap with ground-truth definition ranges, cross-repository citation isolation,
and resilience against malformed citation formats.
"""

from pathlib import Path
from typing import Any
import re

from ingestion.repo_walker import chunk_repo
from ingestion.embedder import embed_chunks
from ingestion.hybrid_search import HybridIndex
from backend.generator import (
    prepare_query_context,
    _parse_and_finalize_answer,
    _extract_citations,
    normalize_repo_rel_path,
)


def _parse_citation_parts(citation_str: str) -> tuple[str, int, int] | None:
    """Parse 'path/to/file.ext:start-end' into (rel_path, start_line, end_line)."""
    match = re.match(r"^(.+?):(\d+)(?:-(\d+))?$", citation_str.strip())
    if not match:
        return None
    file_path = match.group(1)
    start_line = int(match.group(2))
    end_line = int(match.group(3)) if match.group(3) else start_line
    return file_path, start_line, end_line


def run_citations_eval(fixtures: dict[str, Any]) -> dict[str, Any]:
    """Evaluate citation grounding precision, boundary correctness, and isolation."""
    results = {
        "category": "Grounded Citations & Source Attribution",
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

    # Ground truth mapping: (symbol, expected_rel_path, min_line, max_line)
    py_repo: Path = fixtures["python"]
    jsts_repo: Path = fixtures["jsts"]
    tenant_a, tenant_b = fixtures["isolation"]

    # 1. Grounded Citations in Python Context
    py_chunks = chunk_repo(str(py_repo), verbose=False)
    embed_chunks(py_chunks, "eval_py_cite")
    py_ctx = prepare_query_context(
        question="Where is validate_amount defined and how does it work?",
        repo_path=str(py_repo),
        repo_id="eval_py_cite",
        top_k=5,
        use_memory=False,
    )

    record_check("Query context prepared successfully", py_ctx is not None)
    if py_ctx:
        record_check("Hit citations generated", len(py_ctx.hit_citations) > 0)
        
        # Verify validate_amount citation
        found_target = False
        for cit in py_ctx.hit_citations:
            parsed = _parse_citation_parts(cit)
            if parsed:
                rel_path, start, end = parsed
                # Check path belongs to repository
                full_file = py_repo / rel_path
                record_check(f"Cited file exists in repository: {rel_path}", full_file.exists())
                # Check coordinate validity
                record_check(f"Citation coordinates valid: {cit}", start > 0 and end >= start)
                # Check line range overlaps ground truth (utils/validators.py lines 3-7)
                if "validators.py" in rel_path:
                    overlaps = not (end < 3 or start > 7)
                    if overlaps:
                        found_target = True
        record_check("Citation accurately overlaps ground truth (utils/validators.py:3-7)", found_target)

    # 2. Grounded Citations in JS/TS Context
    jsts_chunks = chunk_repo(str(jsts_repo), verbose=False)
    embed_chunks(jsts_chunks, "eval_jsts_cite")
    jsts_ctx = prepare_query_context(
        question="Explain CheckoutButton component props and rendering",
        repo_path=str(jsts_repo),
        repo_id="eval_jsts_cite",
        top_k=5,
        use_memory=False,
    )

    record_check("JS/TS query context prepared", jsts_ctx is not None)
    if jsts_ctx:
        found_tsx = False
        for cit in jsts_ctx.hit_citations:
            parsed = _parse_citation_parts(cit)
            if parsed:
                rel_path, start, end = parsed
                full_file = jsts_repo / rel_path
                record_check(f"TSX cited file exists: {rel_path}", full_file.exists())
                if "CheckoutButton.tsx" in rel_path:
                    overlaps = not (end < 9 or start > 24)
                    if overlaps:
                        found_tsx = True
        record_check("Citation accurately overlaps CheckoutButton.tsx definition range", found_tsx)

    # 3. Cross-Repository Citation Isolation
    chunks_a = chunk_repo(str(tenant_a), verbose=False)
    embed_chunks(chunks_a, "eval_tenant_a_cite")
    ctx_a = prepare_query_context(
        question="How is calculate_fee implemented?",
        repo_path=str(tenant_a),
        repo_id="eval_tenant_a_cite",
        top_k=5,
        use_memory=False,
    )

    if ctx_a:
        for cit in ctx_a.hit_citations:
            record_check(
                "Tenant A citation does not leak Tenant B paths",
                "tenant_beta" not in cit and "eval_tenant_beta" not in cit,
                f"Citation: {cit}"
            )

    # 4. Citation Parsing & Normalization Robustness
    test_json_with_cits = """{
        "answer": "validate_amount validates input.",
        "citations": [
            "utils/validators.py:22-26",
            "[utils/validators.py:22-26]",
            "services/payment.py:43",
            "nonexistent/ghost.py:10-20"
        ],
        "confidence": 0.95
    }"""

    parsed_res = _parse_and_finalize_answer(
        content=test_json_with_cits,
        question="validate amount",
        repo_path=str(py_repo),
        repo_id="eval_py_cite",
        hits=py_ctx.hits if py_ctx else [],
        hit_citations=py_ctx.hit_citations if py_ctx else [],
        dep_context=py_ctx.dep_context if py_ctx else "",
        graph=py_ctx.index.graph if py_ctx else None,
        use_memory=False,
    )

    cits = parsed_res.get("citations", [])
    record_check("Citations sanitized and deduplicated", len(cits) >= 2)
    record_check("Brackets stripped from citations", all(not c.startswith("[") and not c.endswith("]") for c in cits))
    record_check("Standard format preserved (path:start-end)", any("utils/validators.py:22-26" in c for c in cits))

    # 5. Invalid / Malformed Format Rejection
    raw_bad_cits = "No valid citations here [random text] (also invalid)"
    extracted = _extract_citations(raw_bad_cits)
    record_check("Malformed citation strings extract zero false positives", len(extracted) == 0, f"Extracted: {extracted}")

    acc = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "citation_grounding_accuracy_pct": round(acc, 2),
        "total_citation_checks": results["total_checks"],
    }

    return results
