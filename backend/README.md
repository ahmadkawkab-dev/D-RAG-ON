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

### Password reset email

The login screen supports a six-digit, expiring password-reset code:

- `POST /api/v1/auth/password-reset/request`
- `POST /api/v1/auth/password-reset/confirm`

Configure delivery with the following `.env` values (all settings use the
`RAG_` prefix):

```dotenv
RAG_SMTP_HOST=smtp.example.com
RAG_SMTP_PORT=587
RAG_SMTP_FROM_EMAIL=no-reply@example.com
RAG_SMTP_USERNAME=your-smtp-user
RAG_SMTP_PASSWORD=your-smtp-password
RAG_SMTP_STARTTLS=true
RAG_SMTP_USE_SSL=false
RAG_PASSWORD_RESET_EXPIRE_MINUTES=10
RAG_PASSWORD_RESET_MAX_ATTEMPTS=5
RAG_PASSWORD_RESET_RESEND_SECONDS=60
```

Use STARTTLS for port 587, or set `RAG_SMTP_USE_SSL=true` and
`RAG_SMTP_STARTTLS=false` for implicit TLS (commonly port 465). Production
requires `RAG_SMTP_HOST`. In development only, when SMTP is omitted, the reset
code is written to the backend log so the flow can be tested locally.

### Account settings

Authenticated account routes are:

- `GET /api/v1/users/me`
- `PATCH /api/v1/users/me`
- `POST /api/v1/users/me/password`
- `GET /api/v1/users/me/usage`

Avatar uploads accept PNG, JPEG, or WebP data URLs up to 512 KB. Password changes
require the current password. Usage reports conversation, message, assistant
answer, and submitted-feedback counts.

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
