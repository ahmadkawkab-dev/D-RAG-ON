# Security and endpoint reference

## Trust boundary

The web UI calls only the .NET API. .NET validates its own JWT, resolves the
application user, applies rate/concurrency limits, audits the outcome, and
forwards the request to Python with server-controlled internal headers. Python
is not a browser authentication server.

## Public .NET endpoints

| Method and path | Access | Purpose |
| --- | --- | --- |
| `GET /api/auth/login/google` | Anonymous, rate limited | Begin Google OAuth |
| `GET /api/auth/google/complete` | Anonymous callback, rate limited | Complete external login |
| `POST /api/auth/refresh` | Refresh cookie, rate limited | Rotate refresh token and issue access token |
| `GET /api/auth/me` | JWT | Current application user |
| `POST /api/auth/logout` | JWT/refresh cookie | Revoke refresh token |
| `POST /api/rag/general/stream` | JWT, RAG limits | General SSE conversation |
| `POST /api/rag/general/answers/select` | JWT, RAG limits | Persist a server-cached general-answer choice |
| `POST /api/rag/document/stream` | JWT, RAG limits | Document-grounded SSE conversation |
| `POST /api/rag/documents/upload` | JWT, RAG limits | Upload and index one PDF |
| `GET /api/rag/history/sessions` | JWT, RAG limits | List owned sessions |
| `GET /api/rag/history/sessions/{sessionId}` | JWT, RAG limits | Read owned session |
| `DELETE /api/rag/history/sessions/{sessionId}` | JWT, RAG limits | Delete owned session |
| `PUT /api/rag/feedback/messages/{messageId}` | JWT, RAG limits | Save owned-message feedback |
| `GET /api/admin/audit-logs` | JWT with `Admin` role | Query bounded audit pages |
| `GET /health` | Anonymous | Basic process status |
| `GET /health/live` | Anonymous | Liveness |
| `GET /health/ready` | Anonymous | MongoDB readiness |

Swagger is registered only in Development at `/swagger`. Its authorization
control accepts the .NET bearer token. It does not define or request
`X-RAG-API-Key`.

## Internal Python endpoints

All `/api/v1/*` routes require the shared internal service key and a validated
application-user header. They should be reachable only from .NET:

| .NET route | Python destination |
| --- | --- |
| `/api/rag/general/stream` | `/api/v1/general/stream` |
| `/api/rag/general/answers/select` | `/api/v1/general/answers/select` |
| `/api/rag/document/stream` | `/api/v1/chat/stream` |
| `/api/rag/documents/upload` | `/api/v1/documents/upload` |
| `/api/rag/history/*` | `/api/v1/history/*` |
| `/api/rag/feedback/*` | `/api/v1/feedback/*` |

## Validation limits

- RAG message: 1–10,000 characters and not whitespace-only.
- Session/message identifiers: 1–128 alphanumeric or hyphen characters.
- Feedback: direction `up` or `down`, at most 20 chips, each 1–64 characters,
  and at most 2,000 comment characters.
- Upload: exactly one `.pdf`, exact `application/pdf`, `%PDF-` signature,
  non-empty, at most 10 MiB.
- Kestrel request body: 11 MiB, leaving multipart framing overhead.
- Headers: 32 KiB total; header timeout: 15 seconds; JSON depth: 32.

Error bodies contain stable codes and a trace identifier where applicable.
Unhandled exception messages and stack traces are never returned.
