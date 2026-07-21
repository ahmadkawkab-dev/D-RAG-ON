# RAG Setup — Internal Ship Program

Starter project for the **Internal Ship Program** RAG track. It gives you a ready-to-run
environment for building a Retrieval-Augmented Generation (RAG) system with the
**LangChain ecosystem** and **local open-source models** — no API keys, your data never
leaves the machine.

The teaching notebook walks through the **ingestion** half of a RAG pipeline on a real
document (CIS Controls v8) across four stages:

```
PDF → 2.1 Parse → 2.2 Chunk → 2.3 Embed → 2.4 Store → (later: retrieve → rerank → agent)
        unstructured   splitters   bge-small   Weaviate
```

| Stage | What it does | Tool |
|-------|--------------|------|
| **2.1 Parse** | Extract text, tables, and images from the PDF | `langchain-unstructured` (`hi_res`) |
| **2.2 Chunk** | Split into retrieval-sized pieces (char / token / by-title) | `langchain-text-splitters` |
| **2.3 Embed** | Turn chunks into vectors, locally on CPU | `BAAI/bge-small-en-v1.5` |
| **2.4 Store** | Save vectors in a DB you can search by similarity | `langchain-weaviate` + Weaviate |

## Prerequisites

Make sure the following are installed **before** you start.

### 1. Python 3.12+

This project requires Python **3.12 or newer** (see `requires-python` in `pyproject.toml`).

### 2. uv (Python package/environment manager)

Dependencies are managed with [uv](https://docs.astral.sh/uv/). Install it once:

```bash
# Linux / macOS / WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```

uv reads `pyproject.toml` + `uv.lock` and creates an isolated `.venv` for you — you don't
need to manage virtualenvs or `pip` by hand.

### 3. System packages for hi-res PDF parsing

`unstructured` uses OCR and a layout model to detect tables and images. Install these
system libraries (Debian / Ubuntu / WSL):

```bash
sudo apt-get update && sudo apt-get install -y poppler-utils tesseract-ocr libgl1
```

| Package | Why it's needed |
|---------|-----------------|
| `poppler-utils` | renders PDF pages to images |
| `tesseract-ocr` | reads text from those images (OCR) |
| `libgl1` | shared library the layout/vision model needs |

> On macOS use Homebrew instead: `brew install poppler tesseract`.

### 4. Docker (for Weaviate, recommended)

The vector database stage uses **Weaviate**. Running it in Docker is the recommended path
(an embedded fallback exists, but Docker is more reliable). Install
[Docker](https://docs.docker.com/get-docker/), then start Weaviate:

```bash
docker run -p 8080:8080 -p 50051:50051 cr.weaviate.io/semitechnologies/weaviate:1.27.0
```

## Setup

From the `rag_setup/` directory:

```bash
# 1. Install Python dependencies into an isolated .venv
uv sync

# 2. Launch Jupyter
uv run jupyter lab        # or: uv run jupyter notebook
```

Open [`notebooks/01_RAG_setup.ipynb`](notebooks/01_RAG_setup.ipynb), select this project's
`.venv` as the kernel, and run the cells top to bottom.

> **First run is slow (one-time):** it downloads the embedding model (~130 MB) and the
> layout model, and `hi_res` parsing of the full PDF takes a few minutes on CPU. Everything
> is cached afterward.

## Optional MinerU2.5 visual parsing

PyMuPDF remains the authoritative parser and its existing chunks are never
replaced. MinerU2.5 can be enabled as a second, visual pass that adds
provenance-marked supplement chunks for difficult pages such as image-heavy
content and CIS summary tables.

Install the optional runtime:

```bash
uv sync --extra mineru
```

Run selective assistance (recommended):

```bash
uv run python main.py ingest data/document.pdf \
  --mineru-mode selective \
  --mineru-device auto \
  --mineru-max-pages 12 \
  --save-jsonl generated_chunks
```

Use `--mineru-pages 4,9-12` to force specific one-based pages or
`--mineru-mode all` for every page. Results are cached under
`.mineru_cache/`. The model is loaded lazily and explicitly unloaded before
EmbeddingGemma starts, so the two models do not intentionally share accelerator
memory.

The supported default is the official
`opendatalab/MinerU2.5-2509-1.2B` model (not a 0.9B release). Its first use
downloads the weights. Review the model's AGPL-3.0 license before redistribution
or deployment.

## Project layout

```
rag_setup/
├── data/                        # CIS Controls v8 PDF (sample document)
├── notebooks/
│   └── 01_RAG_setup.ipynb       # ingestion pipeline walkthrough
├── parsing_workspace.py         # upload/configure/review/export Streamlit UI
├── json_review_workspace.py     # JSON/JSONL golden-candidate quality gate
├── dashboard.py                 # complete RAG operations console
├── parse.py                     # authoritative PyMuPDF parser and chunker
├── main.py                      # ingestion, query, and evaluation CLI
├── pyproject.toml               # dependencies + Python version
└── uv.lock                      # pinned dependency versions
```

## RAG operations console

Start the complete local UI:

```bash
uv run streamlit run app.py
```

The responsive console provides Ask, Evaluate, Documents, Golden Set, and Runs workspaces through a horizontally scrollable section rail. A compact top-left system dock reports CPU/RAM/disk/GPU and local-service health, while the warm beige/ivory/indigo interface follows a 60–30–10 visual balance.

In **Evaluate → Review JSON candidates**, upload JSON or JSONL candidate records. The in-session review normalizes common field names, checks duplicates, frozen-corpus alignment, stable chunk IDs, and answer support, then recommends **Ready to add**, **Human review**, or **Do not add**. Nothing enters the golden set without explicit human confirmation.

In **Document studio → Parse & review**, upload multiple PDFs, adjust
`PipelineConfig` in the sidebar, and follow five measured parser stages. Each
stage exposes timing, strategy settings, inputs, counts, and outputs—including
extracted lines/characters, boilerplate patterns, heading tiers, table annotations,
final chunks, and token statistics. The chunk browser includes token and character
counts, page coverage, implementation groups, text previews, complete metadata,
canonical JSONL, and a downloadable processing manifest. Results remain in session
memory and expensive parses are cached by PDF content and configuration.

Background ingestion and evaluation runs expose the same structured run reporting
under **Runs**, including model/configuration choices, stage progress, indexed chunk
and token totals, output artifact paths, and downloadable JSON reports.

Interactive questions use a resident, serialized query engine. It keeps the
embedding client and lightweight 0.6B reranker warm, bypasses reranking for
high-confidence exact clause lookups, and streams Ollama answer tokens into the
chat-style Streamlit interface. Larger 4B reranking remains an adaptive fallback
for uncertain or multi-evidence questions. Completed responses are cached
locally for 24 hours, so an identical normalized question with identical settings
can return immediately. High-confidence paraphrases can reuse a cached response
after one query embedding, with clause-number and similarity safeguards.
Related-topic questions receive a newly generated answer but stay on the fast
0.6B path. Slow 4B escalation is opt-in for interactive chat and remains enabled
as the evaluation quality reference.


Rebuild the parser-aligned safe evaluation set with:

```bash
uv run python -m scripts.golden_dataset_tools optimize golden_dataset.jsonl data/CIS_Controls__v8__Critical_Security_Controls__2023_08.pdf -o golden_dataset.optimized.jsonl
```

## FastAPI and React readiness

The RAG services can support a React, Vite, and Tailwind CSS frontend while Streamlit remains the operations console. See [FastAPI and Frontend Readiness](docs/FASTAPI_FRONTEND_READINESS.md) for the API boundaries, job model, security controls, endpoint plan, and rollout checklist.

See the [RAG roadmap](docs/RAG_ROADMAP.md) for the recommended quality, efficiency, and functionality plan.
