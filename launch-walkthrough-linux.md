# Launch Walkthrough — Linux (Ubuntu / CachyOS)

This guide covers installing prerequisites and launching the app on **Ubuntu** (or other Debian-based distros) and **CachyOS** (Arch-based). Pick the tab that matches your distro in Step 1, then follow Steps 2 onward as normal — they're identical across distros.

---

## 1. Install Prerequisites

### Runtime & tools needed
- .NET SDK 10
- Python 3.12 or newer
- Node.js (LTS) + npm
- Docker Engine & Docker Compose (plugin or standalone binary)
- Ollama (optional, for local model hosting)
- System libs: `poppler-utils`, `tesseract-ocr`, `libgl1` (or distro equivalents)

### Option A — Ubuntu / Debian-based

```bash
# System libraries
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr libgl1 curl build-essential

# Python 3.12+
sudo apt-get install -y python3.12 python3.12-venv python3-pip

# Node.js LTS (via NodeSource)
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs

# .NET SDK 10
curl -fsSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
chmod +x dotnet-install.sh
./dotnet-install.sh --channel 10.0
echo 'export PATH="$HOME/.dotnet:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Docker Engine + Compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Ollama (optional)
curl -fsSL https://ollama.com/install.sh | sh
```

### Option B — CachyOS (Arch-based)

```bash
# Update system
sudo pacman -Syu

# System libraries
sudo pacman -S --needed poppler tesseract mesa curl base-devel

# Python 3.12+
sudo pacman -S --needed python python-pip

# Node.js LTS + npm
sudo pacman -S --needed nodejs-lts-iron npm

# .NET SDK 10
sudo pacman -S --needed dotnet-sdk
# If dotnet-sdk in the official/CachyOS repos doesn't yet carry SDK 10,
# install it manually instead:
#   curl -fsSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
#   chmod +x dotnet-install.sh && ./dotnet-install.sh --channel 10.0
#   echo 'export PATH="$HOME/.dotnet:$PATH"' >> ~/.bashrc && source ~/.bashrc

# Docker Engine + Compose
sudo pacman -S --needed docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker

# Ollama (optional, via AUR — requires yay or another AUR helper)
yay -S ollama-bin
```

> **Note on Hardware:** Machine learning dependencies (torch, transformers, etc.) require sufficient RAM. A GPU with CUDA drivers is recommended if available. On CachyOS, make sure `nvidia-utils`/`cuda` (or the ROCm equivalent for AMD) is installed if you plan to use GPU acceleration.

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

# Generate a 48-hex-character key and set it in .env
RKEY=$(openssl rand -hex 24)
sed -i "s/^RAG_INTERNAL_API_KEY=.*/RAG_INTERNAL_API_KEY=$RKEY/" .env

# Verify key insertion
head -n 20 .env
```

> **Important:** The .NET middleware variable `RagApi__ApiKey` must match `RAG_INTERNAL_API_KEY`.

---

## 4. Start Infrastructure Containers

Spin up MongoDB and Weaviate using Docker Compose:

```bash
# Using the Docker Compose plugin:
docker compose up -d mongodb weaviate

# Or using standalone docker-compose:
docker-compose up -d mongodb weaviate
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

- [ ] Distro-specific prerequisites installed (Step 1)
- [ ] MongoDB and Weaviate containers are running
- [ ] `.env` file generated with matching `RAG_INTERNAL_API_KEY`
- [ ] Python `.venv` active with dependencies installed (`python -m pip install -e .`)
- [ ] Python FastAPI service listening at `127.0.0.1:8000`
- [ ] .NET Middleware authenticated and running
- [ ] Frontend dev server running and accessible via browser
