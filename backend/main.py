import json
import os
import secrets
import shutil
import stat
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from git import Repo
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from backend.generator import (
    answer_question,
    stream_answer_question,
    clear_conversation_memory,
    get_cached_repo_analysis,
    get_conversation_history,
    invalidate_repo_cache,
)
from ingestion.embedder import delete_collection, embed_chunks
from ingestion.graph_builder import _find_matches, blast_radius, build_graph, callers_of, callees_of
from ingestion.repo_walker import chunk_repo

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(title="RepoSage API")

session_secret = os.getenv("SESSION_SECRET_KEY", "reposage-session-secret")
https_only = os.getenv("HTTPS_ONLY", "false").lower() in ("true", "1", "yes")

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    same_site="none",
    https_only=True,
    max_age=60 * 60 * 24 * 7,
)

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
allowed_origins_list = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

cors_kwargs: dict[str, Any] = {
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if allowed_origins_list:
    cors_kwargs["allow_origins"] = allowed_origins_list
else:
    cors_kwargs["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(CORSMiddleware, **cors_kwargs)

STORE_PATH = Path(__file__).resolve().parent / "repo_store.json"
REPO_STORAGE_PATH = Path(__file__).resolve().parent / "repo_storage"
REPO_STORAGE_PATH.mkdir(exist_ok=True, parents=True)

_store_lock = threading.RLock()


def _remove_readonly(func, path, _):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _safe_rmtree(path: Path | str) -> None:
    target = Path(path)
    if target.exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(target, onexc=_remove_readonly)
        else:
            shutil.rmtree(target, onerror=_remove_readonly)


class RepoConnectRequest(BaseModel):
    repo_path: str
    repo_id: str | None = None


class QueryRequest(BaseModel):
    repo_id: str
    question: str
    reset_conversation: bool | None = False


class RepoImportRequest(BaseModel):
    full_name: str | None = None
    owner: str | None = None
    name: str | None = None
    repo_id: str | None = None
    clone_url: str | None = None
    repo_path: str | None = None
    private: bool | None = False


def _safe_repo_id(repo_id: str | None, fallback: str) -> str:
    raw = (repo_id or fallback).strip()
    if not raw:
        return "repo"
    safe = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '-' for ch in raw)
    return safe.strip('-') or 'repo'


def _load_store() -> dict:
    """Thread-safe read of repo_store.json metadata."""
    with _store_lock:
        if not STORE_PATH.exists():
            return {}
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def _save_store(store: dict) -> None:
    """Thread-safe and atomic write to repo_store.json using fsync and atomic rename."""
    with _store_lock:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path_str = tempfile.mkstemp(
            prefix="repo_store_",
            suffix=".tmp",
            dir=str(STORE_PATH.parent)
        )
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, STORE_PATH)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise


def _get_session_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _normalize_repo_metadata(repo_entry: dict[str, Any], repo_id: str) -> dict[str, Any]:
    return {
        "repo_id": repo_id,
        "repo_path": repo_entry.get("repo_path"),
        "repo_name": repo_entry.get("repo_name") or repo_entry.get("name") or repo_id,
        "owner": repo_entry.get("owner") or "unknown",
        "full_name": repo_entry.get("full_name") or repo_entry.get("repo_name") or repo_id,
        "private": repo_entry.get("private", False),
        "language": repo_entry.get("language"),
        "description": repo_entry.get("description"),
        "default_branch": repo_entry.get("default_branch"),
        "updated_at": repo_entry.get("updated_at"),
        "visibility": "private" if repo_entry.get("private") else "public",
        "chunks": repo_entry.get("chunks", 0),
        "files_discovered": repo_entry.get("files_discovered", 0),
        "files_indexed": repo_entry.get("files_indexed", 0),
        "files_skipped": repo_entry.get("files_skipped", 0),
        "embeddings": repo_entry.get("embeddings", 0),
        "errors": repo_entry.get("errors", []),
        "status": repo_entry.get("status", "ready"),
    }


def _ingest_repository(repo_id: str, repo_path: str) -> dict:
    invalidate_repo_cache(repo_id)
    clear_conversation_memory(repo_id)
    store = _load_store()
    record = store.get(repo_id, {})
    record.update({
        "repo_id": repo_id,
        "repo_path": repo_path,
        "status": "preparing",
    })
    store[repo_id] = record
    _save_store(store)

    chunks, stats = chunk_repo(repo_path, verbose=False, return_stats=True)
    record = store.get(repo_id, {})
    record["status"] = "chunking"
    record["chunks"] = len(chunks)
    record["files_discovered"] = stats.get("files_discovered", 0)
    record["files_indexed"] = stats.get("files_indexed", 0)
    record["files_skipped"] = stats.get("files_skipped", 0)
    record["errors"] = stats.get("errors", [])
    store[repo_id] = record
    _save_store(store)

    embeddings_count = embed_chunks(chunks, repo_id)
    record = store.get(repo_id, {})
    record["status"] = "ready"
    record["embeddings"] = embeddings_count
    store[repo_id] = record
    _save_store(store)

    return {
        "repo_id": repo_id,
        "repo_path": repo_path,
        "chunks": len(chunks),
        "embeddings": embeddings_count,
        "files_discovered": stats.get("files_discovered", 0),
        "files_indexed": stats.get("files_indexed", 0),
        "files_skipped": stats.get("files_skipped", 0),
        "errors": stats.get("errors", []),
        "status": "ready",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "project": "RepoSage"}


@app.get("/api/me")
def current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"user": user}


@app.get("/api/auth/github/login")
def github_login(request: Request) -> RedirectResponse:
    client_id = os.getenv("GITHUB_CLIENT_ID")
    redirect_uri = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/api/auth/github/callback")

    if not client_id:
        raise HTTPException(status_code=500, detail="GitHub OAuth is not configured")

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "read:user repo",
        "allow_signup": "true",
        "state": state,
        "prompt": "select_account",
    }
    github_url = "https://github.com/login/oauth/authorize?" + urlencode(params)
    return RedirectResponse(url=github_url)


@app.get("/api/auth/github/callback")
async def github_callback(request: Request) -> RedirectResponse:
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    expected_state = request.session.get("oauth_state")
    request.session.pop("oauth_state", None)

    if not code:
        error_message = quote("GitHub authorization was cancelled.")
        return RedirectResponse(url=f"{frontend_url}/?error={error_message}")

    if not state or state != expected_state:
        error_message = quote("GitHub authorization failed. Invalid OAuth state.")
        return RedirectResponse(url=f"{frontend_url}/?error={error_message}")

    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    redirect_uri = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/api/auth/github/callback")

    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth credentials are not configured")

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "state": state,
            },
            timeout=30,
        )

    token_json = token_response.json()
    access_token = token_json.get("access_token")
    if not access_token:
        error_message = quote("GitHub could not authorize RepoSage. Check the GitHub App configuration.")
        return RedirectResponse(url=f"{frontend_url}/?error={error_message}")

    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            "https://api.github.com/user",
            headers=_github_headers(access_token),
            timeout=30,
        )

    if user_response.status_code != 200:
        error_message = quote("RepoSage could not load your GitHub profile.")
        return RedirectResponse(url=f"{frontend_url}/?error={error_message}")

    user_data = user_response.json()
    request.session["user"] = {
        "login": user_data.get("login"),
        "name": user_data.get("name") or user_data.get("login"),
        "avatar_url": user_data.get("avatar_url"),
        "html_url": user_data.get("html_url"),
        "email": user_data.get("email"),
    }
    request.session["github_token"] = access_token

    return RedirectResponse(url=f"{frontend_url}/auth/callback")


@app.post("/api/auth/logout")
def logout(request: Request) -> JSONResponse:
    request.session.clear()
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/github/repos")
async def github_repositories(request: Request) -> dict:
    user = _get_session_user(request)
    user_login = (user.get("login") or "").strip().lower()
    token = request.session.get("github_token")

    if not token:
        raise HTTPException(status_code=401, detail="GitHub token is missing. Please sign in again.")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos",
            headers=_github_headers(token),
            params={"visibility": "all", "sort": "updated", "per_page": 100},
            timeout=30,
        )

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Unable to fetch repositories from GitHub")

    repos = response.json()
    store = _load_store()
    cleaned = []
    for repo in repos:
        repo_name = (repo.get("name") or "").strip()
        owner_login = (repo.get("owner", {}).get("login") or "").strip()

        # Exclude special GitHub profile README repository (username/username) for any account
        if repo_name and owner_login and repo_name.lower() == owner_login.lower():
            continue
        if repo_name and user_login and repo_name.lower() == user_login:
            continue

        full_name = repo.get("full_name") or ""
        repo_id = full_name.replace("/", "-") if full_name else str(repo.get("id"))
        stored_meta = store.get(repo_id, {})

        cleaned.append({
            "id": repo.get("id"),
            "name": repo.get("name"),
            "full_name": full_name,
            "owner": repo.get("owner", {}).get("login"),
            "private": repo.get("private", False),
            "language": repo.get("language") or stored_meta.get("language"),
            "description": repo.get("description") or stored_meta.get("description"),
            "default_branch": repo.get("default_branch") or "main",
            "updated_at": repo.get("updated_at"),
            "html_url": repo.get("html_url"),
            "clone_url": repo.get("clone_url"),
            "visibility": "private" if repo.get("private") else "public",
            "indexed": stored_meta.get("status") == "ready",
            "chunks": stored_meta.get("chunks", 0),
        })

    return {"repositories": cleaned}


@app.post("/api/repos/import")
async def import_repository(request: Request, payload: RepoImportRequest) -> dict:
    _get_session_user(request)

    repo_id = _safe_repo_id(payload.repo_id, payload.full_name or payload.name or "repo")
    repo_name = payload.name or (payload.full_name.split("/")[-1] if payload.full_name else repo_id)
    owner = payload.owner or (payload.full_name.split("/")[0] if payload.full_name else "unknown")

    store = _load_store()
    if repo_id in store and store[repo_id].get("status") == "ready":
        existing_path = store[repo_id].get("repo_path")
        if existing_path and Path(existing_path).exists():
            return store[repo_id]

    repo_path_value = (payload.repo_path or "").strip()
    clone_url = (payload.clone_url or "").strip()

    if not repo_path_value:
        repo_dir = REPO_STORAGE_PATH / repo_id
        repo_dir.mkdir(exist_ok=True, parents=True)

        if not clone_url and payload.full_name:
            clone_url = f"https://github.com/{payload.full_name}.git"
        if not clone_url:
            raise HTTPException(status_code=400, detail="Missing repository clone URL")

        token = request.session.get("github_token")
        if token and clone_url.startswith("https://github.com/"):
            clone_url = clone_url.replace(
                "https://github.com/",
                f"https://x-access-token:{token}@github.com/",
            )

        if repo_dir.exists() and any(repo_dir.iterdir()):
            _safe_rmtree(repo_dir)

        try:
            Repo.clone_from(clone_url, repo_dir, depth=1)
        except Exception as clone_exc:
            if not repo_dir.exists() or not any(repo_dir.iterdir()):
                raise HTTPException(status_code=500, detail=f"Repository clone failed: {clone_exc}") from clone_exc

        repo_path_value = str(repo_dir)

    repo_path = str(Path(repo_path_value).resolve())
    if not Path(repo_path).exists():
        raise HTTPException(status_code=404, detail=f"Repository path not found: {repo_path}")

    repo_meta = {
        "repo_id": repo_id,
        "repo_path": repo_path,
        "repo_name": repo_name,
        "owner": owner,
        "full_name": payload.full_name or f"{owner}/{repo_name}",
        "private": payload.private if payload.private is not None else False,
        "language": None,
        "default_branch": "main",
        "status": "preparing",
        "chunks": 0,
    }

    store = _load_store()
    store[repo_id] = repo_meta
    _save_store(store)

    try:
        result = _ingest_repository(repo_id, repo_path)
        record = _load_store().get(repo_id, {})
        record.update(repo_meta)
        record.update(result)
        store = _load_store(); store[repo_id] = record; _save_store(store)
        return record
    except Exception as exc:  # pragma: no cover - runtime protection for ingestion failures
        record = _load_store().get(repo_id, {})
        record.update({"status": "failed", "error": str(exc)})
        store = _load_store(); store[repo_id] = record; _save_store(store)
        raise HTTPException(status_code=500, detail=f"Repository ingestion failed: {exc}") from exc


@app.post("/repos/connect")
def connect_repo(request: RepoConnectRequest) -> dict:
    repo_path = request.repo_path
    repo_id = _safe_repo_id(request.repo_id, Path(repo_path).name)

    if not Path(repo_path).exists():
        raise HTTPException(status_code=404, detail=f"Repository path not found: {repo_path}")

    result = _ingest_repository(repo_id, repo_path)
    store = _load_store()
    record = store.get(repo_id, {})
    record.update({
        "repo_id": repo_id,
        "repo_path": repo_path,
        "repo_name": Path(repo_path).name,
        "owner": "local",
        "full_name": repo_path,
        "private": False,
        "status": "ready",
    })
    record.update(result)
    store[repo_id] = record
    _save_store(store)
    return result


@app.get("/api/repos/{repo_id}/status")
def repo_status(repo_id: str) -> dict:
    store = _load_store()
    repo_meta = store.get(repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")
    return {
        "repo_id": repo_id,
        "status": repo_meta.get("status", "ready"),
        "chunks": repo_meta.get("chunks", 0),
        "files_discovered": repo_meta.get("files_discovered", 0),
        "files_indexed": repo_meta.get("files_indexed", 0),
        "files_skipped": repo_meta.get("files_skipped", 0),
        "embeddings": repo_meta.get("embeddings", 0),
        "errors": repo_meta.get("errors", []),
        "updated_at": repo_meta.get("updated_at"),
        "repo_path": repo_meta.get("repo_path"),
    }


@app.get("/api/repos/{repo_id}")
def repo_details(repo_id: str) -> dict:
    store = _load_store()
    repo_meta = store.get(repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")
    return _normalize_repo_metadata(repo_meta, repo_id)


LANGUAGE_MAP = {
    ".py": "python",
    ".ipynb": "jupyter",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".txt": "plaintext",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".xml": "xml",
    ".toml": "toml",
    ".ini": "ini",
    ".env": "properties",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe",
    ".bin", ".pkl", ".joblib", ".h5", ".parquet", ".npy", ".npz",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".pdf", ".ttf", ".woff", ".woff2",
}

IGNORED_TREE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}


def _validate_repo_path(repo_root: Path, rel_path: str) -> Path:
    """Validate that rel_path is a safe relative path strictly inside repo_root."""
    if not rel_path or not rel_path.strip():
        raise HTTPException(status_code=400, detail="File path cannot be empty")

    raw_path = rel_path.strip().replace("\\", "/")

    # Reject absolute paths (Windows drive letters or root slashes)
    if raw_path.startswith("/") or ":" in raw_path or raw_path.startswith("\\"):
        raise HTTPException(status_code=400, detail="Absolute paths are not allowed")

    # Reject path traversal components
    parts = Path(raw_path).parts
    if ".." in parts:
        raise HTTPException(status_code=400, detail="Path traversal is not allowed")

    resolved_file = (repo_root / raw_path).resolve()
    resolved_root = repo_root.resolve()

    try:
        resolved_file.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal is not allowed")

    return resolved_file


@app.get("/api/repos/{repo_id}/tree")
def repo_tree(repo_id: str) -> dict:
    store = _load_store()
    repo_meta = store.get(repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    repo_root = Path(repo_meta["repo_path"]).resolve()
    if not repo_root.exists():
        raise HTTPException(status_code=404, detail=f"Repository path does not exist: {repo_meta['repo_path']}")

    tree: list[dict[str, Any]] = []
    total_files = 0
    total_dirs = 0

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORED_TREE_DIRS and not d.startswith(".")]
        rel_root = Path(root).relative_to(repo_root)

        for directory in sorted(dirs):
            dir_rel_path = (rel_root / directory).as_posix() if rel_root != Path(".") else directory
            tree.append({
                "type": "directory",
                "path": dir_rel_path,
                "name": directory,
            })
            total_dirs += 1

        for filename in sorted(files):
            if filename.startswith("."):
                continue
            file_rel_path = (rel_root / filename).as_posix() if rel_root != Path(".") else filename
            full_file_path = Path(root) / filename
            ext = Path(filename).suffix.lower()
            try:
                size = full_file_path.stat().st_size
            except OSError:
                size = 0

            tree.append({
                "type": "file",
                "path": file_rel_path,
                "name": filename,
                "size": size,
                "extension": ext,
                "language": LANGUAGE_MAP.get(ext, "plaintext"),
            })
            total_files += 1

    return {
        "repo_id": repo_id,
        "items": tree,
        "total_files": total_files,
        "total_dirs": total_dirs,
    }


@app.get("/api/repos/{repo_id}/file")
def repo_file(repo_id: str, path: str) -> dict:
    store = _load_store()
    repo_meta = store.get(repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    repo_root = Path(repo_meta["repo_path"]).resolve()
    target_file = _validate_repo_path(repo_root, path)

    if not target_file.exists() or target_file.is_dir():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    ext = target_file.suffix.lower()
    size = target_file.stat().st_size
    rel_path = target_file.relative_to(repo_root).as_posix()

    if ext in BINARY_EXTENSIONS or size > 5 * 1024 * 1024:
        return {
            "repo_id": repo_id,
            "path": rel_path,
            "name": target_file.name,
            "size": size,
            "is_binary": True,
            "language": "binary",
            "line_count": 0,
            "content": f"[Binary or oversized file ({size:,} bytes) cannot be displayed as text]",
        }

    try:
        raw_bytes = target_file.read_bytes()
        if b"\x00" in raw_bytes[:8000]:
            return {
                "repo_id": repo_id,
                "path": rel_path,
                "name": target_file.name,
                "size": size,
                "is_binary": True,
                "language": "binary",
                "line_count": 0,
                "content": f"[Binary file ({size:,} bytes) cannot be displayed as text]",
            }
        content = raw_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read file: {e}")

    lines = content.splitlines()
    return {
        "repo_id": repo_id,
        "path": rel_path,
        "name": target_file.name,
        "size": size,
        "is_binary": False,
        "language": LANGUAGE_MAP.get(ext, "plaintext"),
        "line_count": len(lines),
        "content": content,
    }


@app.get("/api/repos/{repo_id}/search")
def repo_search(repo_id: str, q: str) -> dict:
    store = _load_store()
    repo_meta = store.get(repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    query = (q or "").strip()
    if not query:
        return {"repo_id": repo_id, "query": q, "results": [], "total_matches": 0}

    query_lower = query.lower()
    results: list[dict[str, Any]] = []
    repo_root = Path(repo_meta["repo_path"]).resolve()

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORED_TREE_DIRS and not d.startswith(".")]
        for filename in sorted(files):
            if filename.startswith("."):
                continue
            ext = Path(filename).suffix.lower()
            if ext in BINARY_EXTENSIONS:
                continue

            file_path = Path(root) / filename
            try:
                if file_path.stat().st_size > 2 * 1024 * 1024:
                    continue
                raw_bytes = file_path.read_bytes()
                if b"\x00" in raw_bytes[:4000]:
                    continue
                text = raw_bytes.decode("utf-8", errors="ignore")
            except Exception:
                continue

            rel_path = file_path.relative_to(repo_root).as_posix()
            name_matches = query_lower in filename.lower()

            line_matches = []
            for line_idx, line in enumerate(text.splitlines(), start=1):
                if query_lower in line.lower():
                    line_matches.append({
                        "line": line_idx,
                        "text": line.strip()[:160],
                    })
                    if len(line_matches) >= 5:
                        break

            if name_matches or line_matches:
                results.append({
                    "path": rel_path,
                    "name": filename,
                    "line": line_matches[0]["line"] if line_matches else 1,
                    "matches": line_matches,
                    "name_match": name_matches,
                })
                if len(results) >= 50:
                    break

        if len(results) >= 50:
            break

    return {
        "repo_id": repo_id,
        "query": q,
        "results": results,
        "total_matches": len(results),
    }


@app.post("/query")
def query_repo(request: QueryRequest) -> dict:
    store = _load_store()
    repo_meta = store.get(request.repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {request.repo_id}")

    if request.reset_conversation:
        clear_conversation_memory(request.repo_id)

    result = answer_question(request.question, repo_meta["repo_path"], repo_id=request.repo_id)
    return result


@app.post("/query/stream")
def query_repo_stream(request: QueryRequest) -> StreamingResponse:
    store = _load_store()
    repo_meta = store.get(request.repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {request.repo_id}")

    if request.reset_conversation:
        clear_conversation_memory(request.repo_id)

    return StreamingResponse(
        stream_answer_question(
            request.question,
            repo_meta["repo_path"],
            repo_id=request.repo_id
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/repos/{repo_id}/conversation/reset")
@app.post("/query/reset")
def reset_repo_conversation(repo_id: str) -> dict:
    clear_conversation_memory(repo_id)
    return {"repo_id": repo_id, "conversation_cleared": True}


@app.get("/graph/{repo_id}/{function_name:path}")
def graph_for_function(repo_id: str, function_name: str) -> dict:
    store = _load_store()
    repo_meta = store.get(repo_id)
    if not repo_meta:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    cached = get_cached_repo_analysis(repo_id, repo_meta["repo_path"])
    if cached is not None:
        graph = cached.index.graph
    else:
        chunks = chunk_repo(repo_meta["repo_path"], verbose=False)
        graph = build_graph(chunks, repo_path=repo_meta["repo_path"])

    matches = _find_matches(graph, function_name)
    if not matches:
        return {
            "target_node": None,
            "callers": [],
            "callees": [],
            "blast_radius": {},
            "matches": [],
            "ambiguous": False,
        }

    # If multiple matches exist, pick the best exact match or first match as primary target
    clean_target = function_name.strip().strip("'\"`").rstrip("():;").strip()
    target = matches[0]
    for m in matches:
        m_sym = m.split("::")[-1] if "::" in m else m
        if m_sym.lower() == clean_target.lower() or m.lower() == clean_target.lower():
            target = m
            break

    node_data = graph.nodes.get(target, {})
    callers = callers_of(graph, target)
    callees = callees_of(graph, target)
    blast = blast_radius(graph, target, max_depth=2)

    nodes_map = {}
    all_referenced = [target] + callers + callees + list(blast.keys())
    for ref_node in all_referenced:
        nd = graph.nodes.get(ref_node, {})
        if nd:
            nodes_map[ref_node] = {
                "file_path": nd.get("file_path", ""),
                "name": nd.get("name", ref_node.split("::")[-1] if "::" in ref_node else ref_node),
                "chunk_type": nd.get("chunk_type", ""),
                "start_line": nd.get("start_line", 1),
                "end_line": nd.get("end_line", 1),
            }

    return {
        "target_node": target,
        "file_path": node_data.get("file_path", ""),
        "name": node_data.get("name", target.split("::")[-1] if "::" in target else function_name),
        "chunk_type": node_data.get("chunk_type", ""),
        "start_line": node_data.get("start_line", 1),
        "end_line": node_data.get("end_line", 1),
        "callers": callers,
        "callees": callees,
        "blast_radius": blast,
        "nodes": nodes_map,
        "matches": matches,
        "ambiguous": len(matches) > 1,
    }


@app.delete("/repos/{repo_id}")
def delete_repo(repo_id: str) -> dict:
    invalidate_repo_cache(repo_id)
    clear_conversation_memory(repo_id)
    store = _load_store()
    if repo_id not in store:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    del store[repo_id]
    _save_store(store)

    delete_collection(repo_id)
    repo_dir = REPO_STORAGE_PATH / repo_id
    _safe_rmtree(repo_dir)

    return {"deleted": repo_id}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    reload_mode = os.getenv("UVICORN_RELOAD", "true").lower() in ("true", "1", "yes")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=reload_mode)
