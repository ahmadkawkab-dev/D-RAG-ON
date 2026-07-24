# Audit logging

## Architecture and ownership

The .NET API is the authoritative application audit source. It writes structured,
append-only application records to the MongoDB `audit_logs` collection. Python
retains only operational RAG diagnostics and does not validate browser JWTs,
manage application sessions, or create a duplicate user audit trail.

There is no EF Core model, relational table, or migration. The existing
MongoDB-only architecture creates audit indexes through
`MongoIndexInitializer` when the .NET application starts.

Audit writes are awaited but best-effort. A write failure is sent to the normal
`ILogger` operational channel with the action and trace ID; it is not returned
to the browser and does not fail an otherwise successful authentication or RAG
request. This avoids an audit outage becoming an application outage, but it
means a MongoDB outage can create audit gaps.

## Audited events

Authentication events:

- `AUTH_LOGIN_STARTED`
- `AUTH_LOGIN_SUCCESS`
- `AUTH_LOGIN_FAILED`
- `AUTH_REFRESH_SUCCESS`
- `AUTH_REFRESH_FAILED`
- `AUTH_LOGOUT`
- `AUTH_PROFILE_VIEW`
- `AUTH_UNAUTHORIZED`
- `AUTH_FORBIDDEN`
- `AUTH_RATE_LIMITED`

RAG events:

- `RAG_QUERY`
- `RAG_QUERY_FAILED`
- `RAG_HISTORY_LIST`
- `RAG_HISTORY_GET`
- `RAG_HISTORY_DELETE`
- `RAG_FEEDBACK_SAVE`
- `RAG_DOCUMENT_UPLOAD`
- `RAG_REQUEST_FAILED`

Administrative events:

- `ADMIN_AUDIT_LOG_VIEW`

One middleware record is written for each `/api/rag/*` request, including
authorization failures and exceptions. The same middleware audits every
successful or failed `/api/admin/audit-logs` request and `/api/auth/me`.
Other authentication actions write one explicit controller or Google-handler
record. Global operational exception logging must not create a second audit
record.

Python model, retrieval, reranking, indexing, provider, and internal service-key
failures remain operational logs. Health checks, static assets, CORS preflight,
and individual SSE chunks are intentionally not application audit events.

## MongoDB document

Each `audit_logs` document contains:

| Field | Meaning |
| --- | --- |
| `Id` | Server-generated opaque identifier |
| `UserId` | Internal application user ID, or null when anonymous/unresolved |
| `Action` | Stable action constant |
| `Endpoint` | Normalized route template without arbitrary query values |
| `HttpMethod` | HTTP method |
| `RequestSummary` | Bounded, purpose-built non-content metadata |
| `StatusCode` | Final HTTP outcome |
| `IpAddress` | Connection IP after configured framework processing |
| `UserAgent` | Control characters removed; maximum 256 characters |
| `TraceId` | Server trace identifier used for operational correlation |
| `TimestampUtc` | UTC request start time |
| `DurationMs` | Non-negative elapsed request duration |
| `Succeeded` | True only for status 2xx or 3xx without an exception |
| `FailureCode` | Stable high-level code without exception details |

String bounds are enforced when mapping an `AuditLogEntry`; request summaries
are limited to 512 characters. Startup creates indexes for timestamp,
user/timestamp, action/timestamp, status/timestamp, and success/timestamp.
Audit documents have no application update or delete endpoint and are
append-only by application convention.

## Sensitive-data rules

Audit code never generically serializes request or response objects. It does not
read or persist request bodies, response bodies, headers, query-string values,
SSE content, generated answers, document content, exception messages, or stack
traces.

RAG query summaries contain only mode, prompt length, session presence, and
regeneration presence. Feedback summaries contain only direction, chip count,
and comment length. History summaries do not contain session IDs. Admin access
summaries contain page, page size, and the number of filter categories—not
filter values.

The following are never audit fields:

- Authorization headers, JWTs, cookies, or OAuth state/codes
- Google access or refresh tokens
- .NET refresh-token plaintext or hashes
- Google client secrets or JWT signing keys
- Python service or provider credentials
- Raw prompts, generated answers, filenames, or document contents

## IP addresses and forwarded headers

The current application stores `HttpContext.Connection.RemoteIpAddress` in full.
Loopback values are expected locally. Arbitrary `X-Forwarded-For` input is not
trusted because no deployment-specific known proxy or network has been
approved. When deployed behind a known reverse proxy, configure forwarded
headers only for its explicit addresses/networks before enabling that behavior.
Review whether IPs should be truncated, hashed, excluded, or retained for a
shorter period under the organization’s privacy policy.

## Trace correlation and streaming

The audit record uses `Activity.Current.TraceId` when present, otherwise
`HttpContext.TraceIdentifier`. The .NET RAG client forwards that server-created
value to Python as `X-Correlation-Id`; public correlation values are not copied
through.

Streaming requests are timed before proxying and audited in middleware
`finally`, after completion, failure, or practical client cancellation. The
stream is not buffered and no chunks or answer text are captured. High-level
codes include `RAG_STREAM_TIMEOUT`, `RAG_SERVICE_FAILURE`, and
`CLIENT_DISCONNECTED`.

## Admin access

`GET /api/admin/audit-logs` requires the server-issued `Admin` role. Roles are
persisted on `application_users` and copied into the .NET JWT as `role` claims.
The UI cannot assign roles.

To bootstrap an administrator, an authorized database operator can update one
known application user directly. Replace the placeholder with the internal user
ID; never commit a production identity:

```javascript
db.application_users.updateOne(
  { Id: "<internal-user-id>" },
  { $addToSet: { Roles: "Admin" } }
)
```

The user must refresh or sign in again to receive a JWT containing the new role.

The endpoint supports page numbers starting at 1, page sizes from 1 through
100, newest-first stable ordering, and filters for user ID, action, UTC start,
UTC end, success, and HTTP status. Reversed date ranges return a safe `400`.
Returned DTOs contain only fields defined by the audit schema. There are no
public create, update, or delete audit endpoints.

## Retention recommendation

Pending approval by security, privacy, and legal owners, retain application
audit logs for 90 days in the primary MongoDB database, then archive or delete
them according to organizational policy. This balances common investigation
windows against IP/user metadata privacy and storage growth. Consider a shorter
retention period for IP addresses and a longer protected archive for
`ADMIN_AUDIT_LOG_VIEW` events if policy requires it.

No automatic TTL or cleanup is implemented because retention policy was not
approved. A future reviewed cleanup job or archive process should preserve
legal holds and record its own administrative activity.

## Known limitations

- Best-effort writes can be absent during a MongoDB outage.
- Application append-only behavior is not database-level immutability; MongoDB
  credentials and permissions must restrict direct changes.
- No trusted reverse-proxy topology is configured.
- Live Google and service-backed streaming audit checks require local secrets
  and dependencies and are not part of automated tests.
- MongoDB persistence and index creation are verified by build/unit contracts;
  a live database integration run is still required in the target environment.
