"""
Hybrid retrieval for RepoSage (Phase 3b).

Combines BM25 keyword search + semantic search (ChromaDB) + graph
boosting (callers/callees of the top hit), fused with Reciprocal Rank
Fusion (RRF).
"""

import re
import sys

from rank_bm25 import BM25Okapi  # type: ignore

from ingestion.chunker import CodeChunk
from ingestion.embedder import search_semantic
from ingestion.graph_builder import (
    _find_matches,
    _qualified_name,
    build_graph,
    callers_of,
    callees_of,
    normalize_repo_rel_path,
)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())


def _extract_query_symbols(query: str) -> list[str]:
    """Extract candidate function/class/module identifiers from the query string."""
    tokens = [t.strip(".,;:?!()[]'\" ") for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_.]*", query)]
    stop_words = {"what", "which", "where", "how", "does", "the", "this", "that", "calls", "used", "work", "flow", "repo", "repository", "function", "class", "method", "explain", "show"}
    return [t for t in tokens if len(t) > 2 and t.lower() not in stop_words]


COMMON_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves"
}


def _query_tokens(query: str) -> list[str]:
    tokens = _tokenize(query)
    meaningful = [t for t in tokens if t not in COMMON_STOP_WORDS and len(t) > 1]
    return meaningful if meaningful else tokens


class HybridIndex:
    def __init__(self, chunks: list[CodeChunk], repo_id: str, repo_path: str | None = None):
        self.chunks = chunks
        self.repo_id = repo_id
        self.repo_path = repo_path
        self.qualified_names = []
        corpus = []
        for c in chunks:
            qn = _qualified_name(c, repo_path)
            self.qualified_names.append(qn)
            text = f"{c.file_path} {c.name} {c.chunk_type} " + (c.docstring + " " if c.docstring else "") + c.code
            corpus.append(_tokenize(text))
        self.bm25 = BM25Okapi(corpus) if corpus else None
        self.graph = build_graph(chunks, repo_path)
        self._by_qualified = {}
        for qn, c in zip(self.qualified_names, chunks):
            self._by_qualified[qn] = c
            rel_qn = normalize_repo_rel_path(qn, repo_path)
            self._by_qualified[rel_qn] = c
            self._by_qualified[f"{c.file_path}::{c.name}"] = c
            if c.parent_class:
                self._by_qualified[f"{c.file_path}::{c.parent_class}.{c.name}"] = c

    def bm25_search(self, query: str, top_k: int = 5) -> list[str]:
        if self.bm25 is None:
            return []
        scores = self.bm25.get_scores(_query_tokens(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [self.qualified_names[i] for i in ranked[:top_k] if scores[i] > 0]


def _rrf_merge(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.keys(), key=lambda item: scores[item], reverse=True)


def hybrid_search(
    query: str,
    repo_id: str,
    top_k: int = 5,
    index: "HybridIndex | None" = None,
    repo_path: str | None = None,
) -> list[dict]:
    if index is None:
        raise ValueError("hybrid_search requires a prebuilt HybridIndex -- build one with HybridIndex(chunks, repo_id)")

    if repo_path and not getattr(index, "repo_path", None):
        index.repo_path = repo_path

    bm25_names = index.bm25_search(query, top_k=top_k * 2)
    semantic_hits = search_semantic(query, repo_id, top_k=top_k * 2)
    semantic_names = []
    for h in semantic_hits:
        raw_qn = h.get("qualified_name", "")
        norm_qn = normalize_repo_rel_path(raw_qn, repo_path or index.repo_path) if "::" in raw_qn else raw_qn
        semantic_names.append(norm_qn)

    # Graph-targeted symbol resolution: check if query asks about specific symbols in the graph
    graph_targeted: list[str] = []
    for sym in _extract_query_symbols(query):
        matched = _find_matches(index.graph, sym)
        for m in matched:
            if m not in graph_targeted:
                graph_targeted.append(m)
            # Include direct callers & callees of the target symbol
            for neighbor in callers_of(index.graph, m) + callees_of(index.graph, m):
                if neighbor not in graph_targeted:
                    graph_targeted.append(neighbor)

    fused = _rrf_merge([bm25_names, semantic_names, graph_targeted])

    # Multi-hop graph expansion (up to 2 hops for top fused candidates)
    boosted = list(fused)
    for top_hit in fused[:4]:
        neighbors_hop1 = callers_of(index.graph, top_hit) + callees_of(index.graph, top_hit)
        for n in neighbors_hop1:
            if n not in boosted:
                boosted.append(n)
            # 2nd hop expansion
            neighbors_hop2 = callers_of(index.graph, n) + callees_of(index.graph, n)
            for n2 in neighbors_hop2[:3]:
                if n2 not in boosted:
                    boosted.append(n2)

    results = []
    for qn in boosted:
        chunk = index._by_qualified.get(qn)
        if chunk is None:
            # Try fuzzy lookup in _by_qualified
            for key, c_val in index._by_qualified.items():
                if qn.endswith(f"::{c_val.name}") or key.endswith(f"::{qn.split('::')[-1]}"):
                    chunk = c_val
                    break
        if chunk is None:
            continue
        callers = callers_of(index.graph, qn)
        callees = callees_of(index.graph, qn)
        results.append({
            "qualified_name": qn,
            "file_path": chunk.file_path,
            "chunk_type": chunk.chunk_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "code": chunk.code,
            "docstring": chunk.docstring,
            "callers": callers,
            "callees": callees,
        })
        if len(results) >= top_k:
            break
    return results


if __name__ == "__main__":
    from ingestion.repo_walker import chunk_repo
    from ingestion.embedder import embed_chunks

    repo_path = sys.argv[1] if len(sys.argv) > 1 else "../sample_repo"
    query = sys.argv[2] if len(sys.argv) > 2 else "how does refunding work"
    repo_id = sys.argv[3] if len(sys.argv) > 3 else "demo"

    print(f"Chunking {repo_path} ...")
    chunks = chunk_repo(repo_path, verbose=False)

    print(f"Embedding {len(chunks)} chunks (repo_id='{repo_id}') ...")
    embed_chunks(chunks, repo_id)

    print("Building BM25 index + dependency graph ...")
    index = HybridIndex(chunks, repo_id)

    print(f"\nHybrid search: '{query}'\n")
    results = hybrid_search(query, repo_id, top_k=5, index=index)
    for r in results:
        print(f"  {r['qualified_name']}  ({r['file_path']}:{r['start_line']}-{r['end_line']})  [{r['chunk_type']}]")
