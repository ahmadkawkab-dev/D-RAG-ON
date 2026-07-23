D-RAG-ON — README 

One-line summary

A reproducible Retrieval-Augmented Generation (RAG) application consisting of a browser-based frontend, a .NET middleware API, and an internal Python RAG service. MongoDB stores application data and audit logs, Weaviate holds document vectors, and Ollama/local transformer models provide embeddings, reranking, and generation.

Why this repo

This project demonstrates a production-oriented RAG architecture with clear separation between browser, middleware, and internal AI services. It includes ingestion tools, parsing utilities, evaluation tooling, and a developer-focused operations console.

Repository layout (important folders)

- backend/ and backend.main — Python FastAPI internal RAG service
- middleware/ — .NET middleware (browser-facing API)
- frontend/ — Browser UI
- ingestion/, parse.py, parsing_workspace.py — document parsing & ingestion utilities
- docker-compose.yml — MongoDB and Weaviate definitions used for local development
- pyproject.toml — Python dependency manifest
- launch_walkthrough.md — step-by-step launch guide (created separately)

Architecture (high level)

Browser → .NET Middleware → Python RAG Service
                                 ├── MongoDB (persistence)
                                 └── Weaviate / local models

Security note: The internal Python service is only intended to be reachable by the middleware. An internal API key protects the internal endpoints; do not expose the Python service publicly.

Prerequisites

Install the following tools on your development machine:

- .NET SDK 10
- Python 3.12+
- Node.js (LTS) and npm
- Docker Engine and Docker Compose (either `docker compose` plugin or `docker-compose`)
- Ollama (optional, for local model hosting)
- Poppler utilities & Tesseract for PDF parsing (Linux/WSL):
  sudo apt-get update && sudo apt-get install -y poppler-utils tesseract-ocr libgl1

Tip: Heavy Python dependencies (torch, transformers, sentence-transformers) can be slow to install and may require significant disk/RAM. For GPU acceleration, install matching CUDA drivers and a GPU-enabled torch build.

Quickstart — launch locally (copy-paste)

1) Clone the repository and cd into the project root:

   git clone <repo-url>
   cd D-RAG-ON/D-RAG-ON

2) Create a local .env and set the internal API key (keep secret):

   cp .env.example .env
   RKEY=$(openssl rand -hex 24)
   sed -i "s/^RAG_INTERNAL_API_KEY=.*/RAG_INTERNAL_API_KEY=$RKEY/" .env

3) Start infrastructure services (MongoDB and Weaviate):

   # If your Docker supports the compose plugin:
   docker compose up -d mongodb weaviate

   # Or with the standalone binary:
   docker-compose up -d mongodb weaviate

   docker ps  # verify services are running

4) Prepare Python environment and install dependencies:

   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -e .

5) Start the internal Python RAG service (FastAPI):

   # If 'uv' CLI is available:
   uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

   # Or with uvicorn directly:
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

   # Verify OpenAPI (internal only): http://localhost:8000/docs

6) Configure and run the .NET middleware (ensure secrets match):

   # Required environment variables (examples):
   export MongoDb__ConnectionString="mongodb://localhost:27017"
   export MongoDb__DatabaseName="rag_app"
   export RagApi__ApiKey="$RKEY"  # must equal RAG_INTERNAL_API_KEY in .env

   dotnet run --project middleware/src/RagMiddleware.Api

   # Middleware Swagger UI: https://localhost:<middleware-port>/swagger (Development)

7) Frontend (browser):

   cd frontend
   npm install
   npm run dev

   # Open the URL shown by the dev server (commonly http://localhost:3000)

Health checks and tests

- Python internal service: http://localhost:8000/health and /health/ready
- Middleware: /health and /swagger (in Development)

Automated checks (recommended):

   dotnet test middleware/RagMiddleware.sln
   uv run pytest -q
   cd frontend && npm run lint && npm run build

Optional integration tests (service-backed):

   RUN_LIVE_RAG_TESTS=1 uv run pytest -q tests/backend/test_live_integration.py

Environment variables reference (selected)

- RAG_INTERNAL_API_KEY — internal API key used by the middleware to call Python service (keep secret)
- RAG_MONGODB_URI — e.g. mongodb://localhost:27017
- RAG_MONGODB_DATABASE — e.g. rag_app
- RAG_WEAVIATE_HOST — weaviate host (default localhost)
- RAG_OLLAMA_HOST — Ollama host if using Ollama models
- RAG_EMBEDDING_MODEL, RAG_ANSWER_MODEL, RAG_GENERAL_CHAT_MODEL — model names used by the Python service

Operational notes

- The Python API is internal and must not be exposed publicly. The middleware is the only browser-facing layer.
- Document upload endpoints strictly validate file type/size (PDF only, max 10 MiB) and protect original contents from being logged.
- Use Docker Compose volumes to persist Weaviate and MongoDB data between runs.

Troubleshooting

- "docker compose" not found: install the Docker Compose plugin or the standalone `docker-compose` binary.
- dotnet not installed: install .NET SDK 10.
- uv CLI missing: use `python -m uvicorn` to run the Python service.
- npm missing: install Node.js with npm or use nvm.
- Python packages failing to install (torch/transformers): consider installing CPU-only torch or follow platform-specific install docs for CUDA.

Developer & contribution notes

- The repo includes ingestion tooling, notebooks, and evaluation scripts. See `parse.py`, `main.py`, `ingestion/` and `notebooks/` for developer utilities.
- Please do not check secrets into source control. Use environment variables or OS-level secret storage.

References

- launch_walkthrough.md — detailed copy-pasteable walkthrough with troubleshooting and verification steps (created alongside this README)
- docs/ — additional documentation (security, runbook, audit): docs/runbook.md, docs/hardening.md, docs/security-endpoints.md

License

This project is provided under the LICENSE file in the repository root.

---

Next steps

If you want this polished README to replace the existing README.md, I can either:

1) Overwrite README.md with this content (create a backup first), or
2) Commit README_POLISHED.md as an additional file and open a branch/PR with the change.

Which option do you prefer?
