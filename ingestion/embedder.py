"""
Embedding + ChromaDB storage for RepoSage (Phase 3a).

Uses ChromaDB's built-in embedding function (all-MiniLM-L6-v2, run via
lightweight ONNX runtime) instead of the full sentence-transformers +
PyTorch stack. Same model, same embedding quality, far lighter to
install and run.
"""

import logging
from pathlib import Path

import chromadb  # type: ignore

from ingestion.chunker import CodeChunk

logger = logging.getLogger("reposage.embedder")

CHROMA_PATH = str(Path(__file__).parent / "chroma_db")


def _collection_name(repo_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_id)
    return f"repo_{safe}"


def get_client():
    return chromadb.PersistentClient(path=CHROMA_PATH)


def collection_exists(repo_id: str) -> bool:
    client = get_client()
    name = _collection_name(repo_id)
    try:
        client.get_collection(name=name)
        return True
    except Exception:
        return False


def delete_collection(repo_id: str) -> None:
    client = get_client()
    name = _collection_name(repo_id)
    try:
        client.delete_collection(name)
        logger.info(f"Deleted Chroma collection: {name}")
    except Exception as e:
        logger.debug(f"Collection {name} did not exist or could not be deleted: {e}")


def embed_chunks(chunks: list[CodeChunk], repo_id: str) -> int:
    """Embed and store every chunk in a persistent Chroma collection.
    Safe to re-run: clears any existing collection for this repo_id first.
    """
    client = get_client()
    name = _collection_name(repo_id)

    try:
        client.delete_collection(name)
        logger.info(f"Deleted previous Chroma collection before re-embedding: {name}")
    except Exception as e:
        logger.debug(f"Pre-embed cleanup for {name}: {e}")

    collection = client.create_collection(name=name)

    if not chunks:
        return 0

    ids, documents, metadatas = [], [], []
    for i, chunk in enumerate(chunks):
        qualified_name = f"{chunk.file_path}::{chunk.parent_class}.{chunk.name}" if chunk.parent_class else f"{chunk.file_path}::{chunk.name}"
        ids.append(f"{repo_id}::{qualified_name}::{i}")
        doc_text = f"File: {Path(chunk.file_path).name}\nSymbol: {chunk.name}\nType: {chunk.chunk_type}\n" + (chunk.docstring + "\n" if chunk.docstring else "") + chunk.code
        documents.append(doc_text)
        metadatas.append({
            "file_path": chunk.file_path,
            "name": chunk.name,
            "qualified_name": qualified_name,
            "chunk_type": chunk.chunk_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "parent_class": chunk.parent_class or "",
        })

    BATCH = 16
    for start in range(0, len(ids), BATCH):
        end = start + BATCH
        collection.add(ids=ids[start:end], documents=documents[start:end], metadatas=metadatas[start:end])

    return len(ids)


def search_semantic(query: str, repo_id: str, top_k: int = 5) -> list[dict]:
    client = get_client()
    name = _collection_name(repo_id)
    try:
        collection = client.get_collection(name=name)
    except Exception:
        return []

    results = collection.query(query_texts=[query], n_results=top_k)
    ids = results.get("ids")
    metadatas = results.get("metadatas")
    distances = results.get("distances")

    if not ids or not ids[0] or metadatas is None or not metadatas or distances is None or not distances:
        return []

    hits = []
    for id_, meta, dist in zip(ids[0], metadatas[0] or [], distances[0] or []):
        if not meta or not isinstance(meta, dict):
            continue
        hits.append({
            "id": id_,
            "qualified_name": meta.get("qualified_name", ""),
            "file_path": meta.get("file_path", ""),
            "chunk_type": meta.get("chunk_type", ""),
            "start_line": meta.get("start_line", 1),
            "end_line": meta.get("end_line", 1),
            "score": 1 - (dist if dist is not None else 0),
        })
    return hits


if __name__ == "__main__":
    import sys
    from ingestion.repo_walker import chunk_repo

    repo_path = sys.argv[1] if len(sys.argv) > 1 else "../sample_repo"
    repo_id = sys.argv[2] if len(sys.argv) > 2 else "demo"
    query = sys.argv[3] if len(sys.argv) > 3 else "how does refunding work"

    print(f"Chunking {repo_path} ...")
    chunks = chunk_repo(repo_path, verbose=False)
    print(f"Embedding {len(chunks)} chunks into ChromaDB (repo_id='{repo_id}') ...")
    n = embed_chunks(chunks, repo_id)
    print(f"Stored {n} embeddings.\n")

    print(f"Semantic search: '{query}'")
    for hit in search_semantic(query, repo_id, top_k=5):
        print(f"  {hit['score']:.3f}  {hit['qualified_name']}  ({hit['file_path']}:{hit['start_line']}-{hit['end_line']})")
