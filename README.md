# RepoSage

RAG-based multi-repository engineering assistant using hybrid semantic/BM25
search, AST-aware code chunking, and dependency graph analysis.

## IMPORTANT — keep this as your ONLY project folder

Extract this zip to ONE location and work only from there — for example:
`D:\Users\reposage_starter\reposage`

Do not create a second copy anywhere else (e.g. via Claude Code opening a
different folder). If you ever lose track of where your files are, run:
```powershell
Get-ChildItem -Path D:\ -Recurse -Filter "chunker.py" -ErrorAction SilentlyContinue
```
That tells you exactly where your real project lives.

## Setup — Windows (PowerShell)

Run these one line at a time, from inside this extracted folder:

```powershell
py -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Your terminal prompt should now start with `(venv)`.

## Setup — Mac/Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Try it — run these in order, from inside the `ingestion` folder

```powershell
cd ingestion

# Phase 1: AST-aware chunking on one file
python chunker.py ../sample_repo/payments.py

# Phase 1: chunk an entire repo
python repo_walker.py ../sample_repo

# Phase 2: dependency graph + impact analysis
python graph_builder.py ../sample_repo process_payment

# Phase 1+2 combined, one clean demo run
python demo_progress.py ../sample_repo process_payment

# Phase 3: hybrid search (BM25 + semantic + graph boost)
# NOTE: first run downloads a ~90MB embedding model (one-time, needs internet)
python hybrid_search.py ../sample_repo "how does refunding work" demo
```

## Testing against a real repo (recommended for demos)

```powershell
cd ..
git clone --depth 1 https://github.com/psf/requests.git test_repo
cd ingestion
python demo_progress.py ../test_repo/src/requests set_cookie
```

Expected: 19 files, 312 chunks, 292 graph nodes, 495 edges, and a real
blast-radius result for `set_cookie` (5 direct callers, 20+ affected within
2 hops).

## Status

- [x] Phase 0 — project scaffolding
- [x] Phase 1 — AST-aware chunker (`chunker.py`) + repo walker (`repo_walker.py`)
      — validated on psf/requests, 24 files, 0 skipped
- [x] Phase 2 — dependency graph (`graph_builder.py`) — 292 nodes, 495 edges
      on psf/requests; callers/callees/blast-radius all working
- [x] Phase 3 — hybrid retrieval (`embedder.py` + `hybrid_search.py`) —
      ChromaDB semantic search + BM25 keyword search + graph boosting,
      fused with Reciprocal Rank Fusion
- [x] Phase 4 — RAG prompt assembly + LLM call (`backend/generator.py`)
- [x] Phase 5 — FastAPI backend, React frontend
- [x] Phase 6 — evaluation harness (`run_evaluation.py`, 9 evaluation suites)
- [x] Deployment — Docker Compose multi-container deployment

## Deployment (Docker Compose)

RepoSage is containerized with a two-service Docker Compose architecture:
1. **Backend**: Python 3.12-slim FastAPI service running on Uvicorn (single worker process to maintain process-local LRU cache and conversation memory integrity).
2. **Frontend**: Nginx Alpine container serving the compiled React/Vite production bundle and reverse-proxying API routes with unbuffered SSE streaming support.

### Prerequisites
- Docker (version 24.0+) & Docker Compose (v2.20+)
- Groq API key (`GROQ_API_KEY`) from [console.groq.com](https://console.groq.com)
- Optional: GitHub OAuth App credentials (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`)

### 1. Environment Configuration
Create a `.env` file in the root directory (never commit this file):
```bash
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.1-8b-instant

# GitHub OAuth (Optional for GitHub login & import)
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret
GITHUB_REDIRECT_URI=http://localhost:8000/api/auth/github/callback
FRONTEND_URL=http://localhost

# Session Security & CORS
SESSION_SECRET_KEY=generate-a-long-random-secret-key-here
ALLOWED_ORIGINS=http://localhost,http://localhost:5173,http://localhost:80
HTTPS_ONLY=false
PORT=8000
```

> **Note on GitHub OAuth**: `GITHUB_REDIRECT_URI` must match the Authorization callback URL configured in your GitHub OAuth App settings.

### 2. Build and Start Containers
```bash
# Build and launch both containers in detached mode
docker compose up -d --build
```

### 3. Verify Deployment & Health
```bash
# Check container status
docker compose ps

# Test backend health check endpoint
curl http://localhost/health
# Output: {"status":"ok","project":"RepoSage"}
```

- **Web Application**: Access the frontend dashboard at `http://localhost` (or `http://localhost:5173`).
- **Direct Backend API**: Accessible at `http://localhost:8000`.

### 4. Persistent Storage
Docker Compose manages persistent volumes for:
- `reposage_repo_storage`: Stores cloned Git repositories across container restarts.
- `reposage_repo_store`: Stores the `repo_store.json` registry metadata across container recreations.
- `reposage_chroma_db`: Stores ChromaDB vector embeddings and collection metadata.

### 5. Stop and Restart
```bash
# Restart services
docker compose restart

# Stop containers without removing persistent data
docker compose down

# Stop containers and purge volumes (warning: deletes indexed data)
docker compose down -v
```

### 6. Troubleshooting
- **Streaming not displaying incrementally**: Ensure your reverse proxy has `proxy_buffering off;` and `proxy_set_header X-Accel-Buffering no;` configured (pre-configured in `nginx.conf`).
- **Worker concurrency**: Keep `workers: 1` on the backend container. In-memory LRU caching (`_repo_cache`) and multi-turn reference resolution (`_conversation_memory`) are thread-safe within a single process.

