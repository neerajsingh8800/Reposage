"""
Code Intelligence & Dependency Graph Evaluation Module (Phase 6F).
"""

from pathlib import Path
from typing import Any
from ingestion.repo_walker import chunk_repo
from ingestion.graph_builder import (
    build_graph,
    callers_of,
    callees_of,
    blast_radius,
    _find_matches,
)


def run_code_intel_eval(fixtures: dict[str, Path]) -> dict[str, Any]:
    """Evaluate AST caller/callee accuracy, blast radius, module resolution, and class methods."""
    results = {
        "category": "Code Intelligence & Dependency Graph",
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

    # 1. Python Code Intelligence
    py_repo = fixtures["python"]
    py_chunks = chunk_repo(str(py_repo), verbose=False)
    py_graph = build_graph(py_chunks, repo_path=str(py_repo))

    # Python Callers
    val_callers = callers_of(py_graph, "validate_amount")
    record_check(
        "Python validate_amount direct callers correct",
        any("services/payment.py::PaymentProcessor.process_payment" in c for c in val_callers),
        f"Callers: {val_callers}"
    )

    # Python Callees
    proc_callees = callees_of(py_graph, "PaymentProcessor.process_payment")
    record_check(
        "Python process_payment direct callees correct",
        any("utils/validators.py::validate_amount" in c for c in proc_callees) and
        any("services/payment.py::PaymentProcessor.log_payment" in c for c in proc_callees),
        f"Callees: {proc_callees}"
    )

    # Python Blast Radius (checkout -> process_payment -> validate_amount)
    py_blast = blast_radius(py_graph, "validate_amount", max_depth=2)
    record_check(
        "Python validate_amount blast radius hop 1",
        any("services/payment.py::PaymentProcessor.process_payment" in k and v == 1 for k, v in py_blast.items()),
        f"Blast: {py_blast}"
    )
    record_check(
        "Python validate_amount blast radius hop 2 (checkout)",
        any("services/checkout.py::checkout" in k and v == 2 for k, v in py_blast.items()),
        f"Blast: {py_blast}"
    )

    # 2. JavaScript / TypeScript Code Intelligence
    jsts_repo = fixtures["jsts"]
    jsts_chunks = chunk_repo(str(jsts_repo), verbose=False)
    jsts_graph = build_graph(jsts_chunks, repo_path=str(jsts_repo))

    # JS/TS Callers
    ts_val_callers = callers_of(jsts_graph, "validateAmount")
    record_check(
        "TS validateAmount called by PaymentService.processPayment",
        any("services/paymentService.ts::PaymentService.processPayment" in c for c in ts_val_callers),
        f"Callers: {ts_val_callers}"
    )
    record_check(
        "TS validateAmount called by CommonJS legacyHandler",
        any("legacyHandler.js::legacyHandler" in c for c in ts_val_callers),
        f"Callers: {ts_val_callers}"
    )

    # JS/TS Class methods & this.auditLog()
    ts_proc_callees = callees_of(jsts_graph, "PaymentService.processPayment")
    record_check(
        "TS PaymentService.processPayment calls this.auditLog()",
        any("services/paymentService.ts::PaymentService.auditLog" in c for c in ts_proc_callees),
        f"Callees: {ts_proc_callees}"
    )

    # TS Blast Radius (CheckoutButton -> PaymentService.processPayment -> validateAmount)
    ts_blast = blast_radius(jsts_graph, "validateAmount", max_depth=2)
    record_check(
        "TS validateAmount blast radius hop 1",
        any("services/paymentService.ts::PaymentService.processPayment" in k and v == 1 for k, v in ts_blast.items())
    )
    record_check(
        "TS validateAmount blast radius hop 2 (CheckoutButton)",
        any("components/CheckoutButton.tsx::CheckoutButton" in k and v == 2 for k, v in ts_blast.items())
    )

    # 3. Third-party exclusion check (react should not be a node)
    record_check("React not added as fake repository node", "react" not in jsts_graph.nodes)

    accuracy_pct = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "graph_resolution_accuracy_pct": round(accuracy_pct, 2),
        "total_python_nodes": py_graph.number_of_nodes(),
        "total_python_edges": py_graph.number_of_edges(),
        "total_jsts_nodes": jsts_graph.number_of_nodes(),
        "total_jsts_edges": jsts_graph.number_of_edges(),
    }

    return results
