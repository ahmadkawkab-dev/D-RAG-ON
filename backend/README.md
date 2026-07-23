# Internal FastAPI RAG service

The Python API is an internal adapter over the existing local RAG pipeline.
MongoDB stores chat sessions, messages, feedback, and structured citations;
Weaviate remains the retrieval index. The .NET middleware owns browser
authentication, Google OAuth, application users, roles, refresh tokens, and the
authoritative MongoDB audit trail.

## Start locally

```bash
cd /home/ahmad/rag_setup/rag_setup
cp .env.example .env
uv sync
docker compose up -d mongodb weaviate
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

The internal OpenAPI UI is at `http://localhost:8000/docs`; process health is at
`http://localhost:8000/health`. Do not expose the Python listener or its docs to
the public network.

## Internal authentication

All `/api/v1/*` endpoints require headers supplied by .NET:

```text
X-RAG-API-Key: <shared internal service key>
X-Application-User-Id: <trusted .NET application user ID>
X-Correlation-Id: <server trace ID>
```

Set the same secret in Python as `RAG_INTERNAL_API_KEY` and in .NET as
`RagApi:ApiKey`. It must be at least 32 characters. The browser must never
receive or submit this key. The user header is trusted only after constant-time
service-key validation.

## Routes

- `POST /api/v1/general/stream` — general conversation
- `POST /api/v1/chat/stream` — document-grounded conversation
- `POST /api/v1/documents/upload` — bounded PDF ingestion
- `GET /api/v1/history/sessions`
- `GET /api/v1/history/sessions/{session_id}`
- `DELETE /api/v1/history/sessions/{session_id}`
- `PUT /api/v1/feedback/messages/{message_id}`

The general and document routes are deliberately separate. .NET maps
`/api/rag/general/stream` to `/api/v1/general/stream` and
`/api/rag/document/stream` to `/api/v1/chat/stream`.

The upload endpoint accepts one `application/pdf` file up to 10 MiB, verifies
the `.pdf` extension and `%PDF-` signature, writes only to a temporary
server-generated path, and reuses `PDFChunkingPipeline`, `Embedder`,
`get_or_create_collection`, and `upload_chunks`. It does not create a MongoDB
collection or retain the client filename.

## Logging and tests

Python logs operational model, retrieval, indexing, and service-authentication
failures. .NET alone creates application audit records. Never log service keys,
document contents, prompts, generated answers, or raw exception responses.

```bash
uv run pytest -q
uv run python -m compileall -q backend
```

Run live service tests only after MongoDB, Weaviate, Ollama, models, and the
internal key are ready:

```bash
RUN_LIVE_RAG_TESTS=1 uv run pytest -q tests/backend/test_live_integration.py
```
