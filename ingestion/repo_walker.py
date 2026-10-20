"""
Repo-level ingestion for RepoSage.

Walks an entire repository, finds every relevant source file, and runs
the AST-aware chunker (chunker.py) on each one.
"""

import logging
import os
from pathlib import Path
from typing import Any

from ingestion.chunker import (
    CodeChunk,
    chunk_js_ts_file,
    chunk_notebook_file,
    chunk_python_file,
    chunk_text_file,
)

logger = logging.getLogger("reposage.ingestion")

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", "env", ".venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages",
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
}

SOURCE_EXTENSIONS = {
    ".py", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
    ".java", ".go", ".rs",
    ".c", ".cpp", ".cs", ".php", ".rb",
    ".md", ".txt", ".json", ".yaml", ".yml",
}

LANGUAGE_HANDLERS = {
    ".py": chunk_python_file,
    ".ipynb": chunk_notebook_file,
    ".js": chunk_js_ts_file,
    ".jsx": chunk_js_ts_file,
    ".ts": chunk_js_ts_file,
    ".tsx": chunk_js_ts_file,
    ".mjs": chunk_js_ts_file,
    ".cjs": chunk_js_ts_file,
    ".mts": chunk_js_ts_file,
    ".cts": chunk_js_ts_file,
    ".java": chunk_text_file,
    ".go": chunk_text_file,
    ".rs": chunk_text_file,
    ".c": chunk_text_file,
    ".cpp": chunk_text_file,
    ".cs": chunk_text_file,
    ".php": chunk_text_file,
    ".rb": chunk_text_file,
    ".md": chunk_text_file,
    ".txt": chunk_text_file,
    ".json": chunk_text_file,
    ".yaml": chunk_text_file,
    ".yml": chunk_text_file,
}

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # Skip files larger than 2MB to prevent lockfile/binary bloat


def find_source_files(repo_path: str) -> list[str]:
    matches = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in files:
            if filename in SKIP_FILENAMES or filename.startswith("."):
                continue
            ext = Path(filename).suffix.lower()
            if ext in SOURCE_EXTENSIONS:
                full_path = os.path.join(root, filename)
                try:
                    if os.path.getsize(full_path) <= MAX_FILE_SIZE_BYTES:
                        matches.append(full_path)
                    else:
                        logger.info(f"Skipping oversized file: {full_path}")
                except OSError:
                    continue
    return matches


def chunk_repo(
    repo_path: str,
    verbose: bool = True,
    return_stats: bool = False,
) -> Any:
    """Chunk every supported source file in a repository.

    Files that fail to parse are recorded and logged without aborting
    ingestion of the rest of the repository.
    """
    all_chunks: list[CodeChunk] = []
    files = find_source_files(repo_path)
    skipped: list[dict[str, str]] = []

    for file_path in files:
        ext = Path(file_path).suffix.lower()
        handler = LANGUAGE_HANDLERS.get(ext, chunk_text_file)
        try:
            chunks = handler(file_path)
            all_chunks.extend(chunks)
        except Exception as e:
            logger.warning(f"Error chunking file '{file_path}': {e}", exc_info=True)
            skipped.append({"file": file_path, "error": str(e)})

    stats = {
        "files_discovered": len(files),
        "files_indexed": len(files) - len(skipped),
        "files_skipped": len(skipped),
        "chunks": len(all_chunks),
        "errors": skipped,
    }

    if verbose:
        print(f"Walked {repo_path}")
        print(f"  files found:   {len(files)}")
        print(f"  files skipped: {len(skipped)}")
        print(f"  total chunks:  {len(all_chunks)}")
        if skipped:
            print("  skipped files:")
            for item in skipped[:10]:
                print(f"    - {item['file']}: {item['error']}")

    if return_stats:
        return all_chunks, stats

    return all_chunks


if __name__ == "__main__":
    import sys
    from collections import Counter

    target_repo = sys.argv[1] if len(sys.argv) > 1 else "sample_repo"
    chunks = chunk_repo(target_repo)

    print("\nBreakdown by chunk type:")
    counts = Counter(c.chunk_type for c in chunks)
    for chunk_type, n in counts.items():
        print(f"  {chunk_type}: {n}")

    print("\nBreakdown by file:")
    file_counts = Counter(c.file_path for c in chunks)
    for path, n in sorted(file_counts.items()):
        print(f"  {path}: {n} chunks")
