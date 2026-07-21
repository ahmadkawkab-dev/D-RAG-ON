# Codex Repository Guide

## Mission

This repository is a local-first retrieval-augmented generation (RAG) system for
document ingestion, hybrid retrieval, reranking, grounded answer generation, and
evaluation. Keep data and inference local unless a task explicitly requires an
external service.

The current product surfaces are:

- `app.py`: the active Streamlit operations console.
- `main.py`: the canonical ingestion, query, and evaluation CLI.
- `backend/`: FastAPI, MongoDB persistence, JWT auth, SSE chat, and history.
- `app/main.py`: compatibility entry point for `uvicorn app.main:app`.
- `frontend/`: the React 19, TypeScript, Vite, and Tailwind client.

## Start in native WSL

Always begin work in the native Ubuntu WSL environment, not PowerShell, CMD, or
the Windows UNC filesystem view.

```bash
wsl.exe -d Ubuntu
cd /home/ahmad/rag_setup/rag_setup
pwd
git status --short
```

Run Git, `uv`, Python, Docker, Ollama, pytest, and frontend commands from that
native WSL context and use Linux paths. Avoid project tooling through
`\\wsl.localhost\Ubuntu\...`; the UNC bridge can cause ownership,
permissions, encoding, and process-lifecycle failures.

## Runtime and services

- Python 3.12+ is managed with `uv`; do not use ad hoc `pip` installs.
- FastAPI is the HTTP adapter; Pydantic validates all boundaries.
- MongoDB stores users, sessions, messages, and citations.
- Ollama provides local embeddings, answer generation, and evaluation judging.
- Weaviate provides vector and hybrid retrieval.
- Hugging Face Transformers provides local reranking.
- `docker-compose.yml` starts MongoDB and Weaviate.
- Some PDF features require Poppler, Tesseract, and `libgl1`.
- MinerU is optional and installed with `uv sync --extra mineru`.

Do not add cloud inference, telemetry, or API-key requirements without explicit
approval. Never commit secrets or machine-specific credentials.

## Architecture map

- `parse.py` is the authoritative PyMuPDF parser and semantic chunker.
- `mineru_parser.py` may add provenance-marked visual supplement chunks. It must
  not replace or silently alter authoritative PyMuPDF chunks.
- `ingestion/embedder.py` and `ingestion/store.py` own embedding and Weaviate
  persistence.
- `agent.py` owns hybrid retrieval and grounded synthesis primitives.
- `reranker.py` owns model scoring; `rerank_policy.py` owns routing,
  deduplication, and fast/heavy rerank decisions.
- `main.py` orchestrates shared CLI and query behavior. Reuse its plain-Python
  functions instead of duplicating the pipeline in a UI adapter.
- `resident_query.py` serializes interactive queries and keeps lightweight
  resources warm. Preserve its locking and model-lifecycle intent.
- `response_cache.py` owns exact and guarded semantic response reuse.
- `backend/api/v1/endpoints/` contains thin auth, chat, and history routers.
- `backend/core/` owns settings and cryptography; `backend/db/` owns client
  lifecycle; `backend/models/` and `backend/schemas/` separate persistence
  documents from public contracts.
- `backend/services/` owns Mongo chat persistence, RAG orchestration, async LLM
  streaming, citation normalization, and SSE encoding.
- `background_tasks.py`, `job_runner.py`, and `dashboard.py` retain Streamlit
  background work, run state, reporting, and presentation.
- `eval.py` owns deterministic retrieval metrics and local DeepEval judging.

Keep every interface thin over shared services. Do not duplicate retrieval,
ingestion, evaluation, or review logic across FastAPI, React, Streamlit, or CLI.
Track the backend direction in `docs/BACKEND_GOALS.md`.

## Non-negotiable invariants

1. Keep heavyweight model phases sequential. Explicitly release Ollama,
   Transformers, CPU, and CUDA resources before loading the next heavy model;
   this repository is designed to avoid concurrent-model OOM failures.
2. Preserve stable chunk IDs, source metadata, page ranges, clause numbers,
   breadcrumbs, table annotations, and provenance through parsing, indexing,
   retrieval, caching, and evaluation.
3. Keep generated answers grounded in retrieved context, retain numbered
   citations, and use the established exact abstention response when context is
   insufficient.
4. Treat parser configuration and aligned benchmark inputs as reproducibility
   contracts. A parser or chunk-ID change requires corresponding alignment and
   regression verification.
5. Never auto-approve or silently append golden-set candidates. Human review of
   the question, answer, source support, duplicates, and chunk alignment is
   required.
6. Enforce chat-session ownership in every query and mutation. Never trust a
   client-supplied user ID.
7. Keep JWT secrets server-side, distinguish access and refresh token types, and
   never log credentials, tokens, hashes, or private message content.
8. Emit SSE events in `metadata`, `delta`, then `done` order and persist the
   complete assistant message with the exact structured citations emitted.
9. Keep safe client errors separate from internal tracebacks.
10. Do not expose arbitrary service hosts, model IDs, paths, commands, wildcard
    credentialed CORS, or Mongo/Weaviate clients to browsers.

## Editing guidance

- Inspect the working tree first and preserve unrelated user changes. This
  repository commonly contains large PDFs, notebooks, model outputs, and run
  artifacts; do not rewrite or delete them incidentally.
- Prefer typed, testable services and dependency injection. Keep FastAPI routers
  limited to HTTP concerns and Streamlit state at the presentation boundary.
- Use async MongoDB calls; isolate synchronous model and Weaviate work from the
  event loop and preserve the global model-execution lock.
- Use `pathlib.Path`, UTF-8, deterministic serialization, and atomic replacement
  for persisted JSON/JSONL where practical.
- Validate configuration at boundaries. Keep `retrieve_k`, `top_n`, `alpha`,
  thresholds, file limits, and model choices internally consistent.
- Preserve the current adaptive reranking behavior: exact/high-confidence cases
  stay on the light path, uncertain or multi-evidence cases may escalate, and
  irrelevant results are rejected before generation.
- Avoid editing derived or runtime content unless the task explicitly targets
  it: `.rag_runs/`, `.deepeval/`, caches, `chunks/`, `generated_chunks/`,
  `frontend/dist/`, `frontend/node_modules/`, and model/vector-store data.
- Keep documentation and CLI help synchronized when commands, defaults,
  configuration, artifact schemas, or user-visible workflows change.
- For frontend work, preserve keyboard accessibility and responsive behavior,
  keep backend contracts typed, and do not simulate a backend response once an
  API integration is expected.

## Common commands

Run these from the repository root unless noted otherwise.

```bash
uv sync

docker compose up -d mongodb weaviate

uv run uvicorn backend.main:app --reload
# Compatibility: uv run uvicorn app.main:app --reload

uv run streamlit run app.py

uv run python main.py ingest \
  data/CIS_Controls__v8__Critical_Security_Controls__2023_08.pdf \
  --save-jsonl generated_chunks

uv run python main.py query "What does CIS Control 5 require?" --answer

uv run python main.py eval golden_dataset.current.aligned.jsonl \
  --stages retrieval rerank --skip-judge --limit 3

uv run pytest

cd frontend
npm run dev
npm run lint
npm run build
```

Model-backed commands require the expected Ollama models and a running Ollama
service. Retrieval and ingestion require Weaviate. Do not mistake a missing
local service or model for a unit-test failure.

## Verification expectations

- Start with the narrowest relevant test, then run `uv run pytest` for shared
  Python changes.
- Backend changes should exercise `tests/backend/`; auth tests must cover token
  type/expiry and protected-route failures, while history tests must cover
  cross-user isolation.
- Parser changes should exercise `tests/test_parsing_workspace.py` and, when
  relevant, `tests/test_mineru_parser.py`.
- Query-policy or caching changes should exercise `tests/test_rerank_policy.py`
  and `tests/test_response_cache.py`.
- Background-job or reporting changes should exercise
  `tests/test_background_tasks.py` and `tests/test_dashboard_progress.py`.
- Golden-review changes should exercise `tests/test_json_review_workspace.py`.
- Streamlit changes should retain the existing `streamlit.testing.v1.AppTest`
  smoke coverage.
- Frontend changes should pass both `npm run lint` and `npm run build`.
- Run live ingestion, query, MinerU, or full LLM-judge evaluation only when the
  change warrants the cost and the required local services/models are present.
- Report checks that were not run and why; never imply an external-service or
  model-backed path was verified when only unit tests ran.

## Completion checklist

Before handing off a change:

- Confirm the implementation uses the existing shared boundary rather than a
  parallel pipeline.
- Confirm model lifecycle, grounding, provenance, stable IDs, and human-review
  guarantees remain intact.
- Run proportionate tests and frontend checks.
- Review the diff for generated artifacts, secrets, large binaries, and
  unrelated edits.
- Summarize behavior changes, validation performed, and any remaining service-
  or model-dependent verification.
