# RAG application

This repository contains a browser UI, a public .NET middleware API, and an
internal Python RAG service. MongoDB is the established persistence layer for
application users, refresh tokens, audit records, chat sessions, messages, and
feedback. Weaviate stores document vectors; Ollama and local Transformer models
provide embedding, reranking, and generation.

The browser communicates only with .NET:

```text
Browser → .NET middleware → Python RAG service
                     ├──→ MongoDB
                     └──→ Weaviate / local models
```

The internal service key is attached by the typed .NET client and is never sent
to, accepted from, or stored by the browser.

## Prerequisites

- .NET SDK 10
- Python 3.12 or newer and `uv`
- Node.js and npm
- Docker with Docker Compose
- Ollama with the models configured in `.env`
- Poppler and Tesseract for PDF parsing

On Ubuntu or WSL, the parser dependencies can be installed with:

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr libgl1
```

## Local setup

From the repository root:

```bash
cp .env.example .env
uv sync
docker compose up -d mongodb weaviate
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Configure the .NET secrets outside source control. Environment-variable names
use the standard double-underscore mapping:

```text
MongoDb__ConnectionString
MongoDb__DatabaseName
RagApi__ApiKey
Authentication__Google__ClientId
Authentication__Google__ClientSecret
Authentication__Jwt__SigningKey
```

`RagApi__ApiKey` must equal Python's `RAG_INTERNAL_API_KEY`. Use a random value
of at least 32 characters. Register the Google redirect URI as the middleware
origin plus `/signin-google`; for example,
`https://localhost:7001/signin-google`.

Then start .NET and the UI:

```bash
dotnet run --project middleware/src/RagMiddleware.Api
cd frontend
npm install
npm run dev
```

The middleware Swagger UI is available at `/swagger` only in the Development
environment. Python's internal OpenAPI UI is available at
`http://localhost:8000/docs` and must not be exposed publicly.

## Stable routing contract

These routes are intentionally distinct and must remain unchanged:

| Browser-facing .NET route | Internal Python route |
| --- | --- |
| `POST /api/rag/general/stream` | `POST /api/v1/general/stream` |
| `POST /api/rag/document/stream` | `POST /api/v1/chat/stream` |
| `POST /api/rag/documents/upload` | `POST /api/v1/documents/upload` |

Document upload accepts exactly one `application/pdf` file, validates its
extension and PDF signature, limits it to 10 MiB, assigns a server-generated
identifier, and passes it through the existing parse/embed/Weaviate pipeline.
Original filenames and document contents are not written to application audit
logs.

## Health, tests, and operations

- `/health` and `/health/live`: process liveness
- `/health/ready`: MongoDB readiness
- `docs/security-endpoints.md`: endpoint and authorization reference
- `docs/hardening.md`: security controls and deployment assumptions
- `docs/runbook.md`: deployment, rollback, and troubleshooting
- `docs/audit-logging.md`: MongoDB audit schema and retention guidance

Run the default automated checks:

```bash
dotnet test middleware/RagMiddleware.sln
uv run pytest -q
cd frontend && npm run lint && npm run build
```

Service-backed Python tests are opt-in:

```bash
RUN_LIVE_RAG_TESTS=1 uv run pytest -q tests/backend/test_live_integration.py
```

## Existing RAG tools

The parser, ingestion CLI, notebooks, evaluation tools, and Streamlit operations
console remain available. `parse.py` is the authoritative PDF parser,
`main.py` contains ingestion/query/evaluation commands, and `app.py` starts the
operations console:

```bash
uv run streamlit run app.py
```

Optional MinerU support can be installed with `uv sync --extra mineru`. It adds
provenance-marked supplemental visual chunks and does not replace the
authoritative PyMuPDF output.
