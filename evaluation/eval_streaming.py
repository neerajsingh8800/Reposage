"""
Streaming Protocol Evaluation Module (Phase 6F).

Evaluates SSE streaming protocol, event sequencing, token accumulation,
structured completion payloads, error recovery, and optional live LLM streaming.
"""

import os
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

from backend.generator import stream_answer_question


class _MockChoice:
    def __init__(self, content: str):
        self.delta = type("Delta", (), {"content": content})()


class _MockChunk:
    def __init__(self, content: str):
        self.choices = [_MockChoice(content)]


def _mock_stream_generator(json_text: str, chunk_size: int = 4):
    """Yield incremental chunks to simulate an LLM streaming response."""
    for i in range(0, len(json_text), chunk_size):
        yield _MockChunk(json_text[i : i + chunk_size])


def run_streaming_eval(
    repo_path: str,
    repo_id: str = "eval_streaming_repo",
    live_llm: bool = False,
) -> dict[str, Any]:
    """
    Evaluate SSE streaming protocol.
    
    Deterministic evaluations use controlled mock streaming and require NO network or API key.
    Optional live LLM streaming is evaluated only when live_llm=True and GROQ_API_KEY is configured.
    """
    results = {
        "category": "SSE Streaming Protocol",
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

    # =========================================================================
    # 1. Deterministic Mocked SSE Stream
    # =========================================================================
    mock_response_json = json.dumps({
        "answer": "validate_amount checks that the numerical amount is greater than zero.",
        "citations": ["utils/validators.py:22-26"],
        "confidence": 0.95
    })

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_stream_generator(mock_response_json)

    with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key_for_evaluation"}), \
         patch("backend.generator.Groq", return_value=mock_client):

        stream_gen = stream_answer_question(
            question="How does validate_amount work?",
            repo_path=repo_path,
            repo_id=repo_id,
            top_k=5,
            use_memory=False,
        )

        events: list[tuple[str, Any]] = []
        tokens: list[str] = []
        complete_payload: dict[str, Any] | None = None

        for chunk in stream_gen:
            lines = chunk.strip().splitlines()
            ev_type = None
            data_json = None
            for line in lines:
                if line.startswith("event: "):
                    ev_type = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        data_json = json.loads(line[6:].strip())
                    except Exception:
                        data_json = line[6:].strip()

            if ev_type:
                events.append((ev_type, data_json))
                if ev_type == "token" and isinstance(data_json, dict):
                    tokens.append(data_json.get("text", ""))
                elif ev_type == "complete" and isinstance(data_json, dict):
                    complete_payload = data_json

        event_sequence = [e[0] for e in events]
        record_check("Stream starts with 'start' event", len(event_sequence) > 0 and event_sequence[0] == "start")
        record_check("Stream emits incremental token events", "token" in event_sequence and len(tokens) > 0)
        record_check("Stream ends with 'complete' event", len(event_sequence) > 0 and event_sequence[-1] == "complete")

        accumulated_answer = "".join(tokens)
        record_check(
            "Accumulated streamed tokens form valid answer text",
            "validate_amount" in accumulated_answer and len(accumulated_answer) > 10,
            f"Accumulated: {accumulated_answer}"
        )

        if complete_payload:
            record_check("Complete payload contains 'answer' field", "answer" in complete_payload)
            record_check("Complete payload contains 'citations' list", isinstance(complete_payload.get("citations"), list))
            record_check("Complete payload contains numeric 'confidence'", isinstance(complete_payload.get("confidence"), (int, float)))
            record_check("Complete payload citations properly formatted", len(complete_payload.get("citations", [])) > 0)
        else:
            record_check("Complete payload received", False, "No complete event emitted")

    # =========================================================================
    # 2. Error Event Handling
    # =========================================================================
    err_client = MagicMock()
    err_client.chat.completions.create.side_effect = ConnectionError("Simulated LLM network timeout")

    with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key"}), \
         patch("backend.generator.Groq", return_value=err_client):

        err_stream = stream_answer_question(
            question="How does validate_amount work?",
            repo_path=repo_path,
            repo_id=repo_id,
            top_k=5,
            use_memory=False,
        )

        err_events = []
        for chunk in err_stream:
            for line in chunk.strip().splitlines():
                if line.startswith("event: "):
                    err_events.append(line[7:].strip())

        record_check("Stream emits 'error' event on backend exception", "error" in err_events, f"Events: {err_events}")

    # =========================================================================
    # 3. Missing API Key Guard
    # =========================================================================
    with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
        no_key_stream = stream_answer_question(
            question="How does validate_amount work?",
            repo_path=repo_path,
            repo_id=repo_id,
            top_k=5,
            use_memory=False,
        )
        no_key_events = [line[7:].strip() for chunk in no_key_stream for line in chunk.strip().splitlines() if line.startswith("event: ")]
        record_check("Stream emits 'error' event when GROQ_API_KEY is missing", "error" in no_key_events)

    # =========================================================================
    # 4. Optional Live LLM Stream (Explicit flag + key required)
    # =========================================================================
    live_evaluated = False
    if live_llm:
        live_key = os.getenv("GROQ_API_KEY")
        if live_key:
            live_stream = stream_answer_question(
                question="How does validate_amount work?",
                repo_path=repo_path,
                repo_id=repo_id,
                top_k=5,
                use_memory=False,
            )
            live_events = [line[7:].strip() for chunk in live_stream for line in chunk.strip().splitlines() if line.startswith("event: ")]
            record_check("Live LLM stream executes successfully", "complete" in live_events, f"Events: {live_events}")
            live_evaluated = True
        else:
            record_check("Live LLM stream skipped (GROQ_API_KEY not configured)", True, "Skipped")
    
    compliance = (results["passed_checks"] / results["total_checks"]) * 100 if results["total_checks"] else 0
    results["metrics"] = {
        "streaming_protocol_compliance_pct": round(compliance, 2),
        "total_mock_tokens_streamed": len(tokens),
        "live_llm_tested": live_evaluated,
    }

    return results
