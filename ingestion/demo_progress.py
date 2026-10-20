"""
RepoSage — Progress Demo

Runs the full working pipeline:
  1. Chunk an entire repo (AST-aware, function/class-level)
  2. Build a dependency graph from those chunks
  3. Answer a real impact-analysis question using the graph

Usage:
    python demo_progress.py <repo_path> <function_name>
"""

import sys
from collections import Counter

from ingestion.repo_walker import chunk_repo
from ingestion.graph_builder import build_graph, callers_of, callees_of, blast_radius


def main():
    if len(sys.argv) < 2:
        print("Usage: python demo_progress.py <repo_path> [function_name]")
        sys.exit(1)

    repo_path = sys.argv[1]
    query_name = sys.argv[2] if len(sys.argv) > 2 else None

    print("=" * 70)
    print("STEP 1: AST-aware chunking + repo walk")
    print("=" * 70)
    chunks = chunk_repo(repo_path, verbose=True)

    type_counts = Counter(c.chunk_type for c in chunks)
    print("\nChunk breakdown:")
    for chunk_type, n in type_counts.items():
        print(f"  {chunk_type}: {n}")

    print("\n" + "=" * 70)
    print("STEP 2: Building the dependency graph")
    print("=" * 70)
    graph = build_graph(chunks)
    print(f"Graph built — nodes: {graph.number_of_nodes()}, edges: {graph.number_of_edges()}")

    if query_name:
        print("\n" + "=" * 70)
        print(f"STEP 3: Impact analysis for '{query_name}'")
        print("=" * 70)
        print(f"\nWho calls '{query_name}'?")
        for c in callers_of(graph, query_name):
            print(f"  - {c}")

        print(f"\nWhat does '{query_name}' call?")
        for c in callees_of(graph, query_name):
            print(f"  - {c}")

        radius = blast_radius(graph, query_name)
        print(f"\nBlast radius of '{query_name}' (functions affected within 2 hops): {len(radius)}")
        for node, dist in list(radius.items())[:10]:
            print(f"  - {node}  ({dist} hop{'s' if dist > 1 else ''} away)")
        if len(radius) > 10:
            print(f"  ...and {len(radius) - 10} more")

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
