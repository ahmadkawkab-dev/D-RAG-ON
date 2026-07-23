# Launch Walkthrough — macOS

This guide covers installing prerequisites and launching the app on macOS (Intel or Apple Silicon) using [Homebrew](https://brew.sh).

---

## 1. Install Prerequisites

### Runtime & tools needed
- .NET SDK 10
- Python 3.12 or newer
- Node.js (LTS) + npm
- Docker Desktop for Mac (includes Docker Compose)
- Ollama (optional, for local model hosting)
- System libs: `poppler`, `tesseract`

### Install Homebrew (if not already installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Install everything else

```bash
# System libraries (poppler-utils + tesseract-ocr equivalents; libgl1 not needed on macOS)
brew install poppler tesseract

# Python 3.12+
brew install python@3.12

# Node.js LTS
brew install node@lts
echo 'export PATH="/opt/homebrew/opt/node@lts/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# .NET SDK 10
brew install --cask dotnet-sdk

# Docker Desktop (includes Compose)
brew install --cask docker
open -a Docker   # launch Docker Desktop once to finish setup and start the daemon

# Ollama (optional)
brew install ollama
```

> **Apple Silicon (M1/M2/M3/M4) note:** All the above formulas/casks have native ARM builds via Homebrew. If you hit an architecture mismatch on any Python package during Step 5, try `arch -arm64 python -m pip install -e .`
>
> **Hardware note:** Machine learning dependencies (torch, transformers, etc.) require sufficient RAM. Apple Silicon Macs can use the `mps` backend for GPU acceleration in PyTorch; no CUDA is available on macOS.

---

## 2. Clone the Repository

```bash
git clone <repo-url>
cd D-RAG-ON/D-RAG-ON
pwd  # Should print the repo root containing README.md
```

---

## 3. Configure `.env` & Generate Internal API Key

The Python backend and .NET middleware authenticate using `RAG_INTERNAL_API_KEY`. Copy `.env.example` and inject a randomly generated secret:

```bash
cp .env.example .env

# Generate a 48-hex-character key and set it in .env (BSD sed syntax on macOS)
RKEY=$(openssl rand -hex 24)
sed -i '' "s/^RAG_INTERNAL_API_KEY=.*/RAG_INTERNAL_API_KEY=$RKEY/" .env

# Verify key insertion
head -n 20 .env
```

> **Important:** The .NET middleware variable `RagApi__ApiKey` must match `RAG_INTERNAL_API_KEY`.
>
> Note the `sed -i ''` syntax above — macOS ships BSD `sed`, which requires an explicit (empty) backup extension argument, unlike GNU `sed` on Linux.

---

## 4. Start Infrastructure Containers

Make sure Docker Desktop is running (check the whale icon in the menu bar), then spin up MongoDB and Weaviate:

```bash
docker compose up -d mongodb weaviate
```

**Verify running containers:**
```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

* **Weaviate:** Reachable at `http://localhost:8080`
* **MongoDB:** Reachable at `mongodb://localhost:27017`

---

## 5. Set Up Python Environment

Create a virtual environment and install the required packages:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# Install main package in editable mode
python -m pip install -e .

# Optional: Install MinerU support
# python -m pip install -e .[mineru]
```

---

## 6. Run the Internal Python Service (FastAPI)

Start the FastAPI application on port `8000`:

```bash
# Option A: If 'uv' CLI is available
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Option B: Direct Uvicorn execution
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

**Verification Endpoints:**
* **OpenAPI Docs:** `http://localhost:8000/docs`
* **Health Check:** `http://localhost:8000/health`
* **Readiness Check (MongoDB):** `http://localhost:8000/health/ready`

---

## 7. Configure and Run the .NET Middleware

Export environment variables into your shell session and run the middleware project:

```bash
export MongoDb__ConnectionString="mongodb://localhost:27017"
export MongoDb__DatabaseName="rag_app"
export RagApi__ApiKey="$RKEY"

# Optional Auth variables (if applicable):
# export Authentication__Google__ClientId="..."
# export Authentication__Google__ClientSecret="..."
# export Authentication__Jwt__SigningKey="..."

dotnet run --project middleware/src/RagMiddleware.Api
```

* **Swagger UI:** Available at `https://localhost:<middleware-port>/swagger` in Development mode.

---

## 8. Launch Frontend Application

Open a **new terminal tab/window**, navigate to `frontend`, install dependencies, and run the development server:

```bash
cd frontend
npm install
npm run dev
```

* Access the web UI at the dev URL (typically `http://localhost:3000`). The frontend communicates strictly with the .NET middleware.

---

## 9. Automated Testing & Verification

Run automated test suites across all components:

```bash
# 1. .NET Middleware tests
dotnet test middleware/RagMiddleware.sln

# 2. Python Backend tests
uv run pytest -q

# 3. Frontend linting & build verification
cd frontend && npm run lint && npm run build
```

**Optional (Live RAG Integration Tests):**
```bash
RUN_LIVE_RAG_TESTS=1 uv run pytest -q tests/backend/test_live_integration.py
```

---

## 10. Minimal Quickstart (Python-Only Mode)

To run only the Python service without full infrastructure or heavy models:

1. Run MongoDB locally or use test mocks.
2. Set feature flags in your environment to use mock backends as defined in `main.py`.

---

## 11. Launch Checklist

- [ ] Homebrew prerequisites installed (Step 1)
- [ ] Docker Desktop running (whale icon active in menu bar)
- [ ] MongoDB and Weaviate containers are running
- [ ] `.env` file generated with matching `RAG_INTERNAL_API_KEY`
- [ ] Python `.venv` active with dependencies installed (`python -m pip install -e .`)
- [ ] Python FastAPI service listening at `127.0.0.1:8000`
- [ ] .NET Middleware authenticated and running
- [ ] Frontend dev server running and accessible via browser
