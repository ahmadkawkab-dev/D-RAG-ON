# Deployment and operations runbook

## Configuration

Provision secrets through the target environment's secret manager:

```text
MongoDb__ConnectionString
MongoDb__DatabaseName
RagApi__ApiKey
Authentication__Google__ClientId
Authentication__Google__ClientSecret
Authentication__Jwt__SigningKey
RAG_INTERNAL_API_KEY
RAG_MONGODB_URI
RAG_MONGODB_DATABASE
```

`RagApi__ApiKey` and `RAG_INTERNAL_API_KEY` must match. Do not print either
value while checking configuration. Register the exact middleware
`/signin-google` callback URI with Google.

MongoDB has no relational migration step. On .NET startup,
`MongoIndexInitializer` creates the required indexes idempotently against the
existing collections. Do not rename, drop, or rewrite collections during
deployment.

## Startup order

1. Start MongoDB and Weaviate.
2. Start Ollama and ensure configured models are available.
3. Start Python on a private listener and verify `/health`.
4. Start .NET and verify `/health/live` and `/health/ready`.
5. Start or deploy the frontend against the .NET origin.
6. In Development only, inspect `/swagger/v1/swagger.json`.

## Smoke checks

1. Confirm an unknown CORS origin is not reflected.
2. Complete Google login and call `/api/auth/me`.
3. Send one general prompt and one document prompt; verify their internal
   destinations remain `/api/v1/general/stream` and `/api/v1/chat/stream`.
4. Upload a small safe PDF through `/api/rag/documents/upload`; confirm an
   indexed result and document-chat retrieval.
5. Confirm an invalid type and a file over 10 MiB are rejected.
6. Confirm an unauthorized RAG request returns `401`, a non-admin audit request
   returns `403`, and repeated requests eventually return `429` with
   `Retry-After`.
7. As an administrator, query `/api/admin/audit-logs` and correlate the trace
   IDs without expecting prompt, answer, filename, or document content.

## Monitoring

Alert on:

- `/health/ready` failure or MongoDB primary-selection errors
- sustained Python `503` or .NET proxy `502`/`503`/`504` responses
- elevated auth failure, forbidden, rate-limited, or RAG failure audit events
- ingestion failures, Weaviate capacity, model latency, and disk pressure
- gaps in expected audit volume during a MongoDB outage

Operational logs may contain trace IDs and stable failure codes, but must not
contain tokens, cookies, service keys, prompts, answers, uploaded content, or
client filenames.

## Common failures

- `ReplicaSetNoPrimary`: verify the MongoDB URI, DNS, TLS, Atlas IP allowlist,
  and cluster availability from the deployment network.
- Python `401`: verify the two internal keys match without logging them and
  confirm the request came through .NET.
- Upload `400`: verify one `.pdf`, exact `application/pdf`, non-empty content,
  and a `%PDF-` signature.
- Upload `413`: reduce the file below 10 MiB; do not increase only one layer's
  limit.
- Upload/index `503`: check parser dependencies, Ollama embedding service,
  Weaviate readiness, and available disk/memory.
- OAuth callback failure: verify the Google client, secret, exact callback URI,
  HTTPS scheme, and external-cookie settings.
- Missing client IP behind a proxy: configure only the proxy's exact address in
  `Proxy:KnownProxies`.

## Rollback

Deploy the previous application artifacts and configuration together. The new
MongoDB indexes and backward-compatible document fields can remain; no
relational rollback or collection migration is required. Do not delete
`application_users`, `refresh_tokens`, `audit_logs`, chat, message, or feedback
collections. If the internal key was rotated, restore or rotate both services
as one operation.
