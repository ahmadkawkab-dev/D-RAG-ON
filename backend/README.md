# FastAPI backend

The backend is an HTTP adapter over the existing local RAG pipeline. MongoDB
stores users, sessions, messages, and structured citations; Weaviate remains the
retrieval index; Ollama and Transformers remain the local model runtimes.

## Start locally

Run every command in native Ubuntu WSL from the repository root:

```bash
cd /home/ahmad/rag_setup/rag_setup
cp .env.example .env
uv sync
docker compose up -d mongodb weaviate
uv run uvicorn backend.main:app --reload
```

The requested compatibility command is also supported:

```bash
uv run uvicorn app.main:app --reload
```

The API documentation is available at `http://localhost:8000/docs`; the health
endpoint is `http://localhost:8000/health`.

Ollama must be running with the configured embedding and answer models before a
chat request. The configured rerankers are loaded locally through Transformers.

## Authentication

Register with JSON:

```text
POST /api/v1/auth/register
{"email":"person@example.com","password":"long-password","full_name":"Person"}
```

Login uses OAuth2 form fields. Send the email in `username`:

```text
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=person@example.com&password=long-password
```

Use the returned access token as `Authorization: Bearer <token>`. Rotate tokens
with `POST /api/v1/auth/refresh`.

## Chat stream

`POST /api/v1/chat/stream` accepts:

```json
{"message": "What does CIS Control 5 require?", "session_id": null}
```

The `text/event-stream` response emits:

```text
event: metadata
data: {"sources":[...]}

event: delta
data: {"content":"token"}

event: done
data: {"session_id":"..."}
```

Metadata contains document ID, title, URL or file path, chunk text, relevance,
page, and section fields suitable for a frontend source accordion.

## History

- `GET /api/v1/history/sessions`
- `GET /api/v1/history/sessions/{session_id}`
- `DELETE /api/v1/history/sessions/{session_id}`

All chat and history endpoints require an access token and enforce session
ownership.

## Tests

The default suite skips service-backed model tests:

```bash
uv run pytest -q
```

Run the repeatable live MongoDB, Weaviate, Ollama, SSE, citation, and history
checks only after local services and models are ready:

```bash
RUN_LIVE_RAG_TESTS=1 uv run pytest -q tests/backend/test_live_integration.py
```
