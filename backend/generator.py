import os
import re
import json
import time
import threading
from typing import Generator, Any
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from ingestion.graph_builder import (
    _find_matches,
    _qualified_name,
    blast_radius,
    callers_of,
    callees_of,
    normalize_repo_rel_path,
)
from ingestion.hybrid_search import HybridIndex, _extract_query_symbols, hybrid_search
from ingestion.repo_walker import chunk_repo


# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# Groq model
DEFAULT_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)


# --------------------------------------------------
# In-Memory Repository Analysis Cache (Phase 6a)
# --------------------------------------------------

MAX_CACHED_REPOS = 5
_cache_lock = threading.RLock()


@dataclass
class CachedRepoAnalysis:
    repo_id: str
    repo_path: str
    chunks: list
    index: HybridIndex
    arch_summary: str = ""


_repo_cache: OrderedDict[str, CachedRepoAnalysis] = OrderedDict()
_analysis_cache = _repo_cache


def get_cached_repo_analysis(
    repo_id: str,
    repo_path: str | Path | None = None
) -> CachedRepoAnalysis | None:
    """Retrieve cached repository analysis if available and valid."""
    with _cache_lock:
        try:
            if repo_id not in _repo_cache:
                return None
            cached = _repo_cache[repo_id]
            if repo_path:
                norm_cached = str(Path(cached.repo_path).resolve())
                norm_query = str(Path(repo_path).resolve())
                if norm_cached != norm_query:
                    del _repo_cache[repo_id]
                    return None
            _repo_cache.move_to_end(repo_id)
            return cached
        except Exception:
            _repo_cache.pop(repo_id, None)
            return None


def set_cached_repo_analysis(
    repo_id: str,
    repo_path: str | Path,
    chunks: list,
    index: HybridIndex,
    arch_summary: str = "",
) -> CachedRepoAnalysis:
    """Store repository analysis in bounded LRU cache."""
    with _cache_lock:
        if repo_id in _repo_cache:
            _repo_cache.move_to_end(repo_id)
        entry = CachedRepoAnalysis(
            repo_id=repo_id,
            repo_path=str(repo_path),
            chunks=chunks,
            index=index,
            arch_summary=arch_summary,
        )
        _repo_cache[repo_id] = entry
        while len(_repo_cache) > MAX_CACHED_REPOS:
            _repo_cache.popitem(last=False)
        return entry


def invalidate_repo_cache(repo_id: str | None = None) -> None:
    """Invalidate cache for a specific repo_id or entire cache if repo_id is None."""
    with _cache_lock:
        if repo_id is None:
            _repo_cache.clear()
        elif repo_id in _repo_cache:
            del _repo_cache[repo_id]


# --------------------------------------------------
# In-Memory Conversation Memory (Phase 6b)
# --------------------------------------------------

MAX_CONVERSATION_TURNS = 10
MAX_CONVERSATION_REPOS = 10
_conversation_lock = threading.RLock()


@dataclass
class ConversationTurn:
    question: str
    answer: str
    functions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


_conversation_memory: OrderedDict[str, list[ConversationTurn]] = OrderedDict()


def get_conversation_history(repo_id: str) -> list[ConversationTurn]:
    """Retrieve bounded conversation history for a repository."""
    with _conversation_lock:
        if repo_id not in _conversation_memory:
            return []
        _conversation_memory.move_to_end(repo_id)
        return list(_conversation_memory[repo_id])


def add_conversation_turn(
    repo_id: str,
    question: str,
    answer: str,
    functions: list[str] | None = None,
    citations: list[str] | None = None,
) -> None:
    """Append a compact conversation turn to the repository history."""
    with _conversation_lock:
        if repo_id in _conversation_memory:
            _conversation_memory.move_to_end(repo_id)
        else:
            _conversation_memory[repo_id] = []

        history = _conversation_memory[repo_id]
        history.append(ConversationTurn(
            question=question,
            answer=answer,
            functions=list(functions or []),
            citations=list(citations or []),
        ))
        if len(history) > MAX_CONVERSATION_TURNS:
            history.pop(0)

        while len(_conversation_memory) > MAX_CONVERSATION_REPOS:
            _conversation_memory.popitem(last=False)


def clear_conversation_memory(repo_id: str | None = None) -> None:
    """Clear conversation history for a specific repository or all repositories."""
    with _conversation_lock:
        if repo_id is None:
            _conversation_memory.clear()
        elif repo_id in _conversation_memory:
            del _conversation_memory[repo_id]


def _resolve_followup_reference(
    question: str,
    history: list[ConversationTurn]
) -> tuple[str, list[str]]:
    """Resolve follow-up pronouns/references from conversation history.
    
    Returns: (augmented_query_for_search, resolved_focus_symbols)
    """
    if not history:
        return question, []

    q_lower = question.lower()
    has_pronoun = any(
        re.search(rf"\b{re.escape(p)}\b", q_lower)
        for p in ["it", "its", "that", "this", "them", "these", "previous", "earlier", "aforementioned"]
    ) or any(
        phrase in q_lower
        for phrase in [
            "that function", "this function", "that method", "this method",
            "that class", "this class", "that file", "this file", "who calls it",
            "what calls it", "what does it call", "what depends on it", "if it changed",
            "if it breaks", "what breaks", "callers of it", "callees of it",
            "where is it", "how does it work", "show it", "explain it"
        ]
    )

    explicit_symbols = _extract_query_symbols(question)

    if has_pronoun or not explicit_symbols:
        for prev in reversed(history[-3:]):
            if prev.functions:
                resolved_symbols = [f for f in prev.functions if f]
                aug_query = f"{question} {' '.join(resolved_symbols[:2])}"
                return aug_query, resolved_symbols

    return question, []


def _build_conversation_context_summary(history: list[ConversationTurn]) -> str:
    """Format compact multi-turn conversation context for prompt."""
    if not history:
        return ""
    lines = []
    for idx, turn in enumerate(history[-3:], start=1):
        lines.append(f"Turn {idx}:")
        lines.append(f"  User Question: {turn.question}")
        ans_preview = turn.answer.split('\n')[0][:200]
        lines.append(f"  Previous Answer Summary: {ans_preview}")
        if turn.functions:
            lines.append(f"  Discussed Symbols: {', '.join(turn.functions[:4])}")
        if turn.citations:
            lines.append(f"  Discussed Files: {', '.join(turn.citations[:4])}")
    return "\n".join(lines)


def _safe_repo_id(
    repo_id: str | None,
    repo_path: str | Path | None
) -> str:

    if repo_id:
        return repo_id

    if repo_path:
        return Path(repo_path).name

    return "default_repo"


def _extract_citations(text: str) -> list[str]:

    pattern = (
        r"(?:[A-Za-z0-9_./\\-]+\.[a-zA-Z0-9_-]+):"
        r"\d+(?:-\d+)?"
    )

    return list(
        dict.fromkeys(
            re.findall(pattern, text)
        )
    )


def _build_repo_architecture_summary(
    chunks: list,
    repo_path: str | Path | None = None
) -> str:
    """Generate a compact, grounded summary of repository structure, modules, and entry points."""
    if not chunks:
        return "No repository chunks available."

    files_set = set()
    dirs_set = set()
    entry_points = []
    classes_and_functions = []

    for c in chunks:
        rel_p = normalize_repo_rel_path(c.file_path, repo_path)
        files_set.add(rel_p)
        parts = rel_p.split("/")
        if len(parts) > 1:
            dirs_set.add(parts[0])

        stem = Path(rel_p).stem.lower()
        if stem in ("main", "app", "index", "server", "cli", "run", "entry"):
            entry_points.append(f"{rel_p} ({c.chunk_type})")
        elif getattr(c, "chunk_type", "") == "function" and getattr(c, "name", "") in ("main", "run", "app", "start", "execute"):
            entry_points.append(f"{rel_p}::{c.name}")

        if getattr(c, "chunk_type", "") in ("class", "function"):
            qn = _qualified_name(c, repo_path) if "::" not in getattr(c, "name", "") else c.name
            classes_and_functions.append(qn)

    entry_points = list(dict.fromkeys(entry_points))[:5]
    top_dirs = sorted(dirs_set)[:6]
    key_symbols = list(dict.fromkeys(classes_and_functions))[:8]

    lines = [
        "Repository Architecture Overview:",
        f"- Structure: {len(files_set)} files across directories: {', '.join(top_dirs) if top_dirs else 'root'}",
    ]
    if entry_points:
        lines.append(f"- Discovered Entry Points: {', '.join(entry_points)}")
    if key_symbols:
        lines.append(f"- Key Symbols: {', '.join(key_symbols)}")

    return "\n".join(lines)


def _build_dependency_and_impact_context(
    question: str,
    results: list[dict],
    graph,
    repo_path: str | Path | None = None,
    extra_symbols: list[str] | None = None,
) -> str:
    """Generate structured dependency callers, callees, and blast radius context for the query."""
    if graph is None or not len(graph.nodes):
        return ""

    q_lower = question.lower()
    is_impact_or_dep_query = any(k in q_lower for k in [
        "what calls", "who calls", "what depends", "depends on", "depend on",
        "affected if", "what would break", "blast radius", "impact of", "used by",
        "uses", "callers", "callees", "downstream", "upstream", "flow through"
    ])

    target_symbols: list[str] = []
    if extra_symbols:
        for sym in extra_symbols:
            matches = _find_matches(graph, sym)
            for m in matches:
                if m not in target_symbols:
                    target_symbols.append(m)

    for token in _extract_query_symbols(question):
        matches = _find_matches(graph, token)
        for m in matches:
            if m not in target_symbols:
                target_symbols.append(m)

    for item in results:
        qn = item.get("qualified_name", "")
        if qn and qn in graph and qn not in target_symbols:
            target_symbols.append(qn)

    if not target_symbols:
        return ""

    dep_lines = ["Dependency & Impact Graph Context:"]
    for sym in target_symbols[:4]:
        callers = callers_of(graph, sym)
        callees = callees_of(graph, sym)
        radius = blast_radius(graph, sym, max_depth=3)

        dep_lines.append(f"- Target: {sym}")
        if callers:
            dep_lines.append(f"  Direct Callers (upstream): {', '.join(callers[:6])}")
        else:
            dep_lines.append("  Direct Callers: None reported in AST graph")

        if callees:
            dep_lines.append(f"  Direct Callees (downstream): {', '.join(callees[:6])}")
        else:
            dep_lines.append("  Direct Callees: None reported in AST graph")

        if radius and (is_impact_or_dep_query or extra_symbols):
            impact_items = [f"{n} (hop {d})" for n, d in list(radius.items())[:6]]
            dep_lines.append(f"  Transitive Blast Radius: {', '.join(impact_items)}")

    return "\n".join(dep_lines)


def _build_context_prompt(
    results: list[dict],
    repo_path: str | Path | None = None,
    arch_summary: str | None = None,
    dep_context: str | None = None,
    conversation_context: str | None = None,
) -> str:

    sections = []

    if conversation_context:
        sections.append(
            "=== CONVERSATION CONTEXT (Reference Only - Not Repository Evidence) ===\n"
            + conversation_context
        )

    sections.append("=== REPOSITORY EVIDENCE (Authoritative Repository Code & Graph Context) ===")

    if arch_summary:
        sections.append(arch_summary)

    if dep_context:
        sections.append(dep_context)

    if results:
        sections.append("Source Code & Documentation Chunks:")
        for item in results:
            rel_path = normalize_repo_rel_path(item["file_path"], repo_path)
            file_path = Path(item["file_path"])
            start_line = int(item.get("start_line", 1))
            end_line = int(item.get("end_line", 1))

            if item.get("code"):
                code = item["code"]
            else:
                try:
                    with open(
                        file_path,
                        "r",
                        encoding="utf-8",
                        errors="replace"
                    ) as f:
                        source_lines = f.readlines()

                    code = "".join(
                        source_lines[
                            start_line - 1:end_line
                        ]
                    )
                except Exception as e:
                    code = (
                        f"[Could not read source code: {e}]"
                    )

            chunk_type = item.get("chunk_type", "code")
            suffix = file_path.suffix.lower()
            if chunk_type in ("notebook_markdown", "doc") or suffix in (".md", ".txt"):
                lang = "markdown"
            elif suffix in (".json", ".yaml", ".yml"):
                lang = suffix.lstrip(".")
            elif suffix in (".js", ".jsx", ".ts", ".tsx"):
                lang = "javascript"
            else:
                lang = "python"

            qn = normalize_repo_rel_path(item.get("qualified_name", ""), repo_path) if "::" in item.get("qualified_name", "") else item.get("qualified_name", "")

            sections.append(
                f"""File: {rel_path}
Lines: {start_line}-{end_line}
Symbol: {qn}
Type: {chunk_type}

Source content:
```{lang}
{code}
```"""
            )
    else:
        sections.append("No specific code context found.")

    return "\n\n".join(sections)


@dataclass
class PreparedQueryContext:
    repo_id: str
    repo_path: str
    question: str
    resolved_query: str
    resolved_symbols: list[str]
    history: list[ConversationTurn]
    index: HybridIndex
    arch_summary: str
    hits: list[dict]
    hit_citations: list[str]
    dep_context: str
    conversation_context: str | None
    context_prompt: str
    system_prompt: str
    user_prompt: str

    @property
    def augmented_question(self) -> str:
        return self.resolved_query


def prepare_query_context(
    question: str,
    repo_path: str | Path,
    repo_id: str | None = None,
    top_k: int = 5,
    use_memory: bool = True,
) -> PreparedQueryContext | None:
    """Prepare repository context, conversation context, hybrid search hits, and LLM prompts."""
    repo_id = _safe_repo_id(repo_id, repo_path)
    repo_path = str(repo_path)

    if not Path(repo_path).exists():
        raise FileNotFoundError(f"Repository path not found: {repo_path}")

    # Retrieve cached analysis or prepare index
    cached = get_cached_repo_analysis(repo_id, repo_path)
    if cached is not None:
        chunks = cached.chunks
        index = cached.index
        arch_summary = cached.arch_summary
    else:
        chunks = chunk_repo(repo_path, verbose=False)
        if not chunks:
            return None

        index = HybridIndex(chunks, repo_id, repo_path=repo_path)
        arch_summary = _build_repo_architecture_summary(chunks, repo_path=repo_path)
        set_cached_repo_analysis(repo_id, repo_path, chunks, index, arch_summary)

    # Multi-turn reference resolution (Phase 6b)
    history = get_conversation_history(repo_id) if use_memory else []
    resolved_query, resolved_symbols = _resolve_followup_reference(question, history)
    conversation_context = _build_conversation_context_summary(history) if history else None

    # Hybrid search
    hits = hybrid_search(resolved_query, repo_id, top_k=top_k, index=index)

    dep_context = _build_dependency_and_impact_context(
        question,
        hits,
        index.graph,
        repo_path=repo_path,
        extra_symbols=resolved_symbols
    )

    hit_citations = [
        f"{normalize_repo_rel_path(hit['file_path'], repo_path)}:{hit['start_line']}-{hit['end_line']}"
        for hit in hits
    ]

    context = _build_context_prompt(
        hits,
        repo_path=repo_path,
        arch_summary=arch_summary,
        dep_context=dep_context,
        conversation_context=conversation_context,
    )

    system_prompt = (
        "You are RepoSage, a code-aware repository assistant. "
        "Answer questions using only the authoritative repository evidence (source code, architecture overview, and dependency graph) provided in the repository context. "
        "If prior conversation context is present, use it solely to understand follow-up references (e.g. 'it', 'that function', 'the previous module'), but do NOT treat prior conversation as repository evidence. "
        "Every factual claim must include an explicit file:line citation in this format: "
        "[path:line-start-line-end] using repository-relative paths from the repository evidence. "
        "When explaining dependency relationships or blast radius, cite the target source files and specify verified callers/callees. "
        "If the answer is not supported by the repository evidence, say 'Not found in repository'. "
        "Do not invent APIs, behaviors, functions, classes, or files. "
        "Return only valid JSON with exactly these keys: answer, citations, confidence. "
        "The confidence value must be a number between 0 and 1. "
        "Do not include markdown. "
        "Do not include explanations outside JSON."
    )

    user_prompt = (
        f"Question: {question}\n\n"
        f"Repository context:\n{context}\n\n"
        "Answer the question using only "
        "the repository context above. "
        "Return valid JSON in exactly this format:\n"
        "{\n"
        '  "answer": "your answer",\n'
        '  "citations": ["path:line-start-line-end"],\n'
        '  "confidence": 0.0\n'
        "}"
    )

    return PreparedQueryContext(
        repo_id=repo_id,
        repo_path=repo_path,
        question=question,
        resolved_query=resolved_query,
        resolved_symbols=resolved_symbols,
        history=history,
        index=index,
        arch_summary=arch_summary,
        hits=hits,
        hit_citations=hit_citations,
        dep_context=dep_context,
        conversation_context=conversation_context,
        context_prompt=context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def _extract_delta_answer(full_raw: str, last_emitted_len: int) -> tuple[str, int]:
    """Extract incremental answer delta text from a streaming JSON or plaintext response."""
    text = full_raw
    if "<think>" in text:
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        else:
            return "", last_emitted_len

    text = re.sub(r"^```(?:json)?\s*", "", text.strip())

    match = re.search(r'"answer"\s*:\s*"', text)
    if match:
        start_idx = match.end()
        idx = start_idx
        while idx < len(text):
            if text[idx] == '\\':
                idx += 2
                continue
            if text[idx] == '"':
                break
            idx += 1
        raw_slice = text[start_idx:idx]

        if raw_slice.endswith('\\'):
            raw_slice = raw_slice[:-1]

        try:
            unescaped = json.loads(f'"{raw_slice}"')
        except Exception:
            unescaped = (
                raw_slice
                .replace('\\"', '"')
                .replace('\\n', '\n')
                .replace('\\t', '\t')
                .replace('\\\\', '\\')
            )

        if len(unescaped) > last_emitted_len:
            delta = unescaped[last_emitted_len:]
            return delta, len(unescaped)
        return "", last_emitted_len

    if len(text) > 30 and not re.search(r'["{\[]', text[:30]):
        if len(text) > last_emitted_len:
            delta = text[last_emitted_len:]
            return delta, len(text)

    return "", last_emitted_len


def _parse_and_finalize_answer(
    content: str,
    question: str,
    repo_path: str,
    repo_id: str,
    hits: list[dict],
    hit_citations: list[str],
    dep_context: str,
    graph: Any,
    use_memory: bool = True,
) -> dict:
    """Parse model JSON response, validate citations, compute confidence, and record conversation turn."""
    content = (content or "").strip()

    if "</think>" in content:
        content = content.split("</think>", 1)[1].strip()

    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content).strip()

    answer_text = content
    parsed: dict[str, Any] = {}

    try:
        parsed = json.loads(answer_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", answer_text, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = {}

        if not parsed:
            ans_match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', answer_text, re.DOTALL)
            if ans_match:
                try:
                    parsed["answer"] = json.loads(f'"{ans_match.group(1)}"')
                except Exception:
                    parsed["answer"] = ans_match.group(1)
            cit_match = re.search(r'"citations"\s*:\s*\[(.*?)\]', answer_text, re.DOTALL)
            if cit_match:
                parsed["citations"] = _extract_citations(cit_match.group(0))

    raw_answer = str(parsed.get("answer", answer_text)).strip()
    is_negative = (
        "not found in repository" in raw_answer.lower()
        or "not found in the repository" in raw_answer.lower()
        or "no information found" in raw_answer.lower()
        or "could not be established" in raw_answer.lower()
    )

    if is_negative:
        final_citations: list[str] = []
        conf_val = 0.0
    else:
        raw_cits = parsed.get("citations", [])
        if isinstance(raw_cits, list) and raw_cits:
            cleaned_cits = []
            for c in raw_cits:
                if isinstance(c, str):
                    clean_c = c.strip().strip("[]()\"' ")
                    if ":" in clean_c:
                        p_part, l_part = clean_c.rsplit(":", 1)
                        cleaned_cits.append(f"{normalize_repo_rel_path(p_part, repo_path)}:{l_part}")
                    else:
                        cleaned_cits.append(normalize_repo_rel_path(clean_c, repo_path))
            final_citations = list(dict.fromkeys(cleaned_cits))
        else:
            final_citations = list(dict.fromkeys(hit_citations))

        raw_conf = parsed.get("confidence", 0.85)
        try:
            model_conf = min(1.0, max(0.0, float(raw_conf)))
        except (ValueError, TypeError):
            model_conf = 0.85

        if final_citations:
            conf_val = round(max(0.75, model_conf), 2)
        elif hits or dep_context:
            conf_val = round(min(0.85, model_conf), 2)
        else:
            conf_val = round(min(0.5, model_conf), 2)

    # Extract identified functions/symbols from graph
    identified_functions = []
    for token in _extract_query_symbols(question):
        matches = _find_matches(graph, token)
        for m in matches:
            node_data = graph.nodes.get(m, {})
            c_type = node_data.get("chunk_type", "")
            # Only identify real functions, methods, classes, or direct symbol matches
            if c_type in ("function", "method", "class") or m.split("::")[-1].lower() == token.lower():
                norm_m = normalize_repo_rel_path(m, repo_path) if "::" in m else m
                identified_functions.append(norm_m)

    unique_functions = list(dict.fromkeys(identified_functions))

    if use_memory:
        add_conversation_turn(
            repo_id=repo_id,
            question=question,
            answer=raw_answer,
            functions=unique_functions,
            citations=final_citations,
        )

    return {
        "answer": raw_answer,
        "citations": final_citations,
        "confidence": conf_val,
        "functions": unique_functions,
    }


def _call_groq_with_retry(client: Groq, **kwargs) -> Any:
    """Execute Groq chat completion with exponential backoff on 429 rate limit."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            if ("429" in err_msg or "rate limit" in err_msg) and attempt < max_retries - 1:
                wait_time = 3.0 * (attempt + 1)
                time.sleep(wait_time)
                continue
            raise


def answer_question(
    question: str,
    repo_path: str | Path,
    repo_id: str | None = None,
    top_k: int = 5,
    use_memory: bool = True,
) -> dict:
    """Retrieve repository context and ask Groq for a citation-grounded answer."""
    prepared = prepare_query_context(
        question=question,
        repo_path=repo_path,
        repo_id=repo_id,
        top_k=top_k,
        use_memory=use_memory,
    )

    if prepared is None:
        return {
            "answer": "Not found in repository",
            "citations": [],
            "confidence": 0.0,
            "functions": [],
        }

    if not prepared.hits and not prepared.dep_context:
        res = {
            "answer": "Not found in repository",
            "citations": [],
            "confidence": 0.0,
            "functions": [],
        }
        if use_memory:
            add_conversation_turn(
                repo_id=prepared.repo_id,
                question=question,
                answer=res["answer"],
                functions=[],
                citations=[],
            )
        return res

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")

    client = Groq(api_key=api_key)

    response = _call_groq_with_retry(
        client,
        model=DEFAULT_MODEL,
        temperature=0.1,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": prepared.system_prompt},
            {"role": "user", "content": prepared.user_prompt},
        ],
    )

    content = response.choices[0].message.content or ""
    return _parse_and_finalize_answer(
        content=content,
        question=question,
        repo_path=prepared.repo_path,
        repo_id=prepared.repo_id,
        hits=prepared.hits,
        hit_citations=prepared.hit_citations,
        dep_context=prepared.dep_context,
        graph=prepared.index.graph,
        use_memory=use_memory,
    )


def stream_answer_question(
    question: str,
    repo_path: str | Path,
    repo_id: str | None = None,
    top_k: int = 5,
    use_memory: bool = True,
) -> Generator[str, None, None]:
    """Stream answer tokens via SSE, then emit final structured result."""
    safe_id = _safe_repo_id(repo_id, repo_path)
    yield f"event: start\ndata: {json.dumps({'repo_id': safe_id})}\n\n"

    try:
        prepared = prepare_query_context(
            question=question,
            repo_path=repo_path,
            repo_id=repo_id,
            top_k=top_k,
            use_memory=use_memory,
        )
    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
        return

    if prepared is None or (not prepared.hits and not prepared.dep_context):
        res = {
            "answer": "Not found in repository",
            "citations": [],
            "confidence": 0.0,
            "functions": [],
        }
        if use_memory and prepared is not None:
            add_conversation_turn(
                repo_id=prepared.repo_id,
                question=question,
                answer=res["answer"],
                functions=[],
                citations=[],
            )
        yield f"event: token\ndata: {json.dumps({'text': 'Not found in repository'})}\n\n"
        yield f"event: complete\ndata: {json.dumps(res)}\n\n"
        return

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        yield f"event: error\ndata: {json.dumps({'message': 'GROQ_API_KEY is not set'})}\n\n"
        return

    client = Groq(api_key=api_key)

    try:
        stream = _call_groq_with_retry(
            client,
            model=DEFAULT_MODEL,
            temperature=0.1,
            max_tokens=1200,
            stream=True,
            messages=[
                {"role": "system", "content": prepared.system_prompt},
                {"role": "user", "content": prepared.user_prompt},
            ],
        )

        full_raw_text = ""
        emitted_len = 0

        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            full_raw_text += delta
            token_delta, emitted_len = _extract_delta_answer(full_raw_text, emitted_len)
            if token_delta:
                yield f"event: token\ndata: {json.dumps({'text': token_delta})}\n\n"

        # Stream completed successfully -> finalize structured result and update conversation memory
        final_result = _parse_and_finalize_answer(
            content=full_raw_text,
            question=question,
            repo_path=prepared.repo_path,
            repo_id=prepared.repo_id,
            hits=prepared.hits,
            hit_citations=prepared.hit_citations,
            dep_context=prepared.dep_context,
            graph=prepared.index.graph,
            use_memory=use_memory,
        )

        yield f"event: complete\ndata: {json.dumps(final_result)}\n\n"

    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"


# =============================================
# COMMAND LINE ENTRY POINT
# =============================================

if __name__ == "__main__":

    import sys

    repo_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "../sample_repo"
    )

    question = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "how does refunding work"
    )

    result = answer_question(
        question,
        repo_path,
        repo_id="demo"
    )

    print(result)