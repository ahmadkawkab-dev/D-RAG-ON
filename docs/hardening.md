# Middleware hardening

## Implemented controls

- HTTPS redirection uses status 307. Production enables HSTS for 30 days.
- Kestrel omits its server header and applies body, header, and timeout limits.
- Responses add `X-Content-Type-Options: nosniff`, a restrictive
  `Referrer-Policy`, `Permissions-Policy`, and same-site resource policy.
- CORS allows only configured explicit HTTP(S) origins, expected headers and
  methods, and credentials. Wildcards, paths, queries, fragments, and embedded
  credentials fail startup validation.
- JWT validation requires issuer, audience, lifetime, signing key, expiration,
  and a signed token. Browser access tokens stay in memory; refresh tokens use
  secure HttpOnly cookies and rotate in MongoDB.
- Fixed-window limits protect auth, OAuth callbacks, and admin reads. A
  token-bucket limit and instance concurrency gate protect RAG endpoints.
  Rejections return `429` with `Retry-After`.
- Central problem details remove exception details from unexpected `500`
  responses and include a server trace ID.
- PDF uploads use a bounded request, exact type checks, a magic signature,
  server-generated identifiers, temporary storage, and the established
  ingestion pipeline.
- MongoDB indexes are created idempotently by `MongoIndexInitializer`.
  No EF Core, SQL provider, relational migration, or alternate user store is
  present.

## Deployment assumptions

TLS should terminate at Kestrel or at an explicitly trusted reverse proxy.
Forwarded headers are disabled unless `Proxy:KnownProxies` contains exact proxy
IP addresses. Never add a public subnet or trust arbitrary
`X-Forwarded-For`/`X-Forwarded-Proto` values.

Expose the .NET listener publicly. Keep Python, MongoDB, Weaviate, and Ollama on
private interfaces or networks. Disable development Swagger in production by
setting `ASPNETCORE_ENVIRONMENT=Production`.

Secrets belong in environment variables or the deployment secret manager, not
`appsettings.json`, `.env.example`, frontend variables, logs, URLs, or source
control. Rotate the shared Python/.NET key together.

## Rate-limit scope

Limits are per process and partition by validated user ID, then remote IP for
anonymous requests. The RAG concurrency gate is also per process and rejects
immediately rather than building an unbounded queue. In a multi-instance
deployment, apply a complementary distributed or edge limit if a global quota
is required.

## Remaining deployment decisions

- Approve production limits from load-test evidence.
- Approve audit and IP retention with security/privacy owners.
- Restrict database credentials and private-network access.
- Confirm backup, restore, and secret-rotation procedures.
- Execute live Google OAuth, MongoDB, Weaviate, Ollama, upload, and SSE smoke
  tests in the target environment.
