# .NET RAG proxy

## Request boundary

The browser calls only the .NET API. The .NET API validates its application JWT, obtains the internal application user ID from the validated `sub` claim, and calls Python with two server-controlled headers:

```text
X-RAG-API-Key: <internal service credential>
X-Application-User-Id: <MongoDB application user ID>
```

The browser cannot set either internal header. The .NET access token is never forwarded to Python. Python validates the service key with a constant-time comparison and uses the trusted user ID only for the existing MongoDB session/history/feedback ownership filters.

## Route mapping

| UI operation | Previous Python endpoint | New .NET endpoint | Python internal endpoint | Streaming |
| --- | --- | --- | --- | --- |
| Document chat | `POST /api/v1/chat/stream` | `POST /api/rag/document/stream` | `POST /api/v1/chat/stream` | SSE |
| General chat | `POST /api/v1/general/stream` | `POST /api/rag/general/stream` | `POST /api/v1/general/stream` | SSE |
| List conversations | `GET /api/v1/history/sessions` | `GET /api/rag/history/sessions` | `GET /api/v1/history/sessions` | No |
| Load conversation | `GET /api/v1/history/sessions/{id}` | `GET /api/rag/history/sessions/{id}` | `GET /api/v1/history/sessions/{id}` | No |
| Delete conversation | `DELETE /api/v1/history/sessions/{id}` | `DELETE /api/rag/history/sessions/{id}` | `DELETE /api/v1/history/sessions/{id}` | No |
| Save feedback | `PUT /api/v1/feedback/messages/{id}` | `PUT /api/rag/feedback/messages/{id}` | `PUT /api/v1/feedback/messages/{id}` | No |

No document upload/list/delete endpoints were invented because the current UI does not call them.

## Client and resilience

`IRagApiClient` is implemented by a typed `HttpClient` registered through `HttpClientFactory`. It has a 15-minute bounded total/attempt timeout for long RAG generations. The retry policy uses bounded exponential backoff with jitter and disables retries for unsafe HTTP methods, so streaming POSTs, feedback PUTs, and deletes are not replayed. Safe GET requests may be retried twice for transient failures.

The proxy streams SSE without buffering and propagates the browser cancellation token. Python response bodies and exception details are not copied into public errors. Public failures use stable codes such as `rag_timeout`, `rag_service_unavailable`, and `rag_service_error`.

## Python service security

The shallow `/health` endpoint remains anonymous and contains no configuration. Every functional Python route requires the internal service key and trusted user context. Python no longer exposes registration, login, refresh, password-reset, or current-user routes and no longer contains browser JWT signing/validation code.

General/document routing and the underlying retrieval, reranking, generation, and streaming implementations are unchanged.
