"""
Conversation Memory Evaluation Module (Phase 6F).
"""

from typing import Any
from backend.generator import (
    add_conversation_turn,
    get_conversation_history,
    clear_conversation_memory,
    prepare_query_context,
    MAX_CONVERSATION_TURNS,
)


def run_memory_eval(repo_path: str, repo_id: str = "eval_memory_repo") -> dict[str, Any]:
    """Evaluate multi-turn conversation memory, 10-turn bounds, and reference resolution."""
    results = {
        "category": "Conversation Memory & Reference Resolution",
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

    clear_conversation_memory(repo_id)

    # 1. Add turns up to boundary
    for i in range(15):
        add_conversation_turn(
            repo_id=repo_id,
            question=f"Question turn {i}",
            answer=f"Answer for turn {i}",
            functions=[f"func_{i}"],
            citations=[f"file_{i}.py:1-10"],
        )

    history = get_conversation_history(repo_id)
    record_check(f"Conversation memory bounded at {MAX_CONVERSATION_TURNS} turns", len(history) == MAX_CONVERSATION_TURNS, f"History length: {len(history)}")
    record_check("Oldest turns evicted (turn 0 evicted, turn 14 present)", history[0].question == "Question turn 5" and history[-1].question == "Question turn 14")

    # 2. Multi-turn reference resolution (anaphora resolution)
    clear_conversation_memory(repo_id)
    add_conversation_turn(
        repo_id=repo_id,
        question="How does validate_amount work?",
        answer="validate_amount checks that the value is positive.",
        functions=["validate_amount"],
        citations=["utils/validators.py:3-7"],
    )

    context = prepare_query_context(
        question="What calls it?",
        repo_path=repo_path,
        repo_id=repo_id,
        top_k=5,
        use_memory=True,
    )

    record_check("Multi-turn context incorporates previous functions", context is not None and "validate_amount" in context.augmented_question)
    record_check("Dependency context populated for referenced function", context is not None and len(context.dep_context) > 0)

    # 3. Clear memory
    clear_conversation_memory(repo_id)
    record_check("Clear memory empties repository history", len(get_conversation_history(repo_id)) == 0)

    success_rate = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "memory_correctness_pct": round(success_rate, 2),
        "max_turn_capacity": MAX_CONVERSATION_TURNS,
    }

    return results
