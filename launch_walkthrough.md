# Launch Walkthrough — D-RAG-ON

This document provides a step-by-step, copy-pasteable walkthrough to launch the D-RAG-ON project locally. It collects the canonical instructions from README.md and expands them with extra verification and troubleshooting guidance.

> Note: Do NOT commit any secrets or the generated `.env` file into source control.

---

## 1. Prerequisites

Install these tools on your machine before beginning:

- .NET SDK 10
- Python 3.12 or newer
- Node.js (LTS) and npm
- Docker (engine) and Docker Compose (either `docker compose` plugin or `docker-compose` binary)
- Ollama (optional, if you plan to use local models referenced in `.env`)
- Poppler utilities & Tesseract for PDF parsing (Linux/WSL):
  ```bash
  sudo apt-get update
  sudo apt-get install -y poppler-utils tesseract-ocr libgl1
  ```

Hardware / extra requirements:
- Installing `torch`, `transformers`, and other ML deps can be heavy; consider using a machine with sufficient RAM and (if desired) GPU + CUDA drivers.

---

## 2. Clone repository and change to project root

If you haven't already cloned the repo, do so. Then cd into the repository root that contains `README.md` and `pyproject.toml`.

```bash
git clone <repo-url>
cd D-RAG-ON/D-RAG-ON
pwd  # should show the repo root containing README.md
```

---

## 3. Create `.env` and set internal API key

The project uses `RAG_INTERNAL_API_KEY` to authenticate the .NET middleware with the internal Python service. Create an `.env` from `.env.example` and generate a strong random key.

```bash
cp .env.example .env
# Generate a 48-hex-character value (example) and insert into .env
RKEY=$(openssl rand -hex 24)
sed -i "s/^RAG_INTERNAL_API_KEY=.*/RAG_INTERNAL_API_KEY=$RKEY/" .env
# Inspect first lines to confirm
head -n 20 .env
```

Important: Keep the value secret. The .NET middleware's `RagApi__ApiKey` must equal `RAG_INTERNAL_API_KEY`.

---

## 4. Start required infrastructure (MongoDB and Weaviate)

Run the docker compose services defined in `docker-compose.yml`:

If your Docker supports the `compose` plugin:

```bash
docker compose up -d mongodb weaviate
```

Or, if your system uses the standalone `docker-compose` binary:

```bash
docker-compose up -d mongodb weaviate
```

Verify services:

```bash
docker ps --format "table {{.Names}}	{{.Image}}	{{.Status}}"
# Weaviate should be reachable at http://localhost:8080
# MongoDB should be available at mongodb://localhost:27017
```

If `docker compose` fails with unknown subcommand, install/enable the Docker Compose plugin or the standalone `docker-compose` binary.

---

## 5. Prepare Python environment and install dependencies

Recommended: use a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
# Install project and dependencies (may take a while)
python -m pip install -e .
# Optional extras (MinerU support):
# python -m pip install -e .[mineru]
```

Notes:
- Installing the full dependency set will download heavy packages (torch, transformers, sentence-transformers, etc.).
- On systems without `uv` CLI, you can run uvicorn directly (see next step).

---

## 6. Start the internal Python RAG service (FastAPI)

Canonical command (project uses a small task runner `uv` in README):

```bash
# If the 'uv' CLI is available (comes from 'uv' package):
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

If `uv` is not available, run uvicorn directly:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify the service:

- Open the OpenAPI docs (internal) at: http://localhost:8000/docs
- Health endpoints:
  - http://localhost:8000/health
  - http://localhost:8000/health/ready  (checks MongoDB readiness)

Security note: The internal Python service must not be exposed to the public. The middleware authenticates to it using the internal API key.

---

## 7. Configure and run the .NET middleware

The middleware requires secrets (set them via environment variables or .NET user secrets). Key variables include:

- `MongoDb__ConnectionString` (e.g. `mongodb://localhost:27017`)
- `MongoDb__DatabaseName` (e.g. `rag_app`)
- `RagApi__ApiKey` (MUST equal `RAG_INTERNAL_API_KEY` from `.env`)
- `Authentication__Google__ClientId` and `Authentication__Google__ClientSecret` (if using Google login)
- `Authentication__Jwt__SigningKey`

Set them in your shell before running `dotnet` (example):

```bash
export MongoDb__ConnectionString="mongodb://localhost:27017"
export MongoDb__DatabaseName="rag_app"
export RagApi__ApiKey="$RKEY"  # make sure this matches RAG_INTERNAL_API_KEY in .env
# export other auth variables as needed

dotnet run --project middleware/src/RagMiddleware.Api
```

The Swagger UI for the middleware (Development environment) will be available at `https://localhost:<middleware-port>/swagger`.

---

## 8. Start the frontend (browser)

Open a new shell and run:

```bash
cd frontend
npm install
npm run dev
```

Open the development URL shown by the dev server (commonly http://localhost:3000). The browser communicates only with the .NET middleware, not directly with Python.

---

## 9. Health checks, verification and automated checks

- Python internal service: http://localhost:8000/health and /health/ready
- Middleware: /health endpoint and Swagger UI (/swagger in Development)

Run automated checks described in README:

```bash
# .NET tests
dotnet test middleware/RagMiddleware.sln
# Python tests
uv run pytest -q
# Frontend lint & build
cd frontend && npm run lint && npm run build
```

Optional service-backed Python tests (run only if services & models are available):

```bash
RUN_LIVE_RAG_TESTS=1 uv run pytest -q tests/backend/test_live_integration.py
```

---

## 10. Troubleshooting & common issues

- docker compose plugin missing: install Docker Desktop or the Compose plugin or the standalone `docker-compose` binary.
- dotnet not found: install .NET SDK 10 from Microsoft.
- `uv` CLI missing: use `python -m uvicorn ...` as an equivalent.
- npm missing: install Node.js including npm (or use nvm to install a Node version that includes npm).
- Python dependency install fails on `torch`/`transformers`: refer to platform-specific installation guidance (CUDA drivers for GPU installs) and consider installing CPU-only torch if needed.
- Ollama: if `.env` references Ollama models, ensure Ollama is running at `RAG_OLLAMA_HOST` and the model names match the host’s available models.
- PDF parsing: ensure `poppler-utils` and `tesseract-ocr` are installed for `parse.py` to work correctly.

---

## 11. Minimal quickstart (Python-only, mocked models)

If you want to run only the Python API without heavyweight models or Weaviate, you can:

- Start MongoDB only (or run with an in-memory mock if available in tests)
- Use environment flags to point to mock backends (this repo includes test helpers; see tests and `main.py` for CLI commands)

This repo contains scripts and test utilities; if a trimmed quickstart is desired, create a separate `quickstart.md` and the minimal environment settings.

---

## 12. Checklist for marking success

- [ ] `docker compose up -d mongodb weaviate` ran successfully
- [ ] `.env` created and `RAG_INTERNAL_API_KEY` set
- [ ] Python venv created and `python -m pip install -e .` finished
- [ ] Python internal FastAPI listening on 127.0.0.1:8000
- [ ] Middleware running and able to call the Python service using the internal key
- [ ] Frontend dev server running and UI reachable in the browser
- [ ] Health endpoints return OK

---

## Want this committed?

If you'd like this file added to the repository and committed, say so and I will create a Git commit and push (or create a branch & PR) including the new `launch_walkthrough.md`. The commit message will include the required Co-authored-by trailer unless you ask otherwise.

---

Document created by an AI assistant (Copilot CLI runtime in VS Code) to help reproduce local launches and make onboarding frictionless.
