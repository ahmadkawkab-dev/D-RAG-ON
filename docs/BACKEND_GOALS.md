# Backend goals and roadmap

## Product vision

Build a secure, local-first RAG platform that exposes the existing ingestion,
retrieval, reranking, generation, and evaluation capabilities through stable
HTTP contracts. MongoDB is the primary application store; Weaviate remains the
retrieval index; Ollama and Transformers remain the local model runtimes.

The backend must be useful to the React client without weakening the existing
Streamlit operations console or CLI.

## Architecture principles

1. Keep FastAPI routers thin and versioned under `/api/v1`.
2. Put orchestration in services, configuration and cryptography in `core`,
   external clients in `db`, persistence documents in `models`, and public
   contracts in `schemas`.
3. Reuse the existing RAG pipeline instead of maintaining a second retrieval or
   reranking implementation.
4. Keep MongoDB authoritative for users and conversations; keep Weaviate
   authoritative for searchable chunks and their retrieval metadata.
5. Run synchronous model and Weaviate work away from the event loop.
6. Serialize heavyweight model phases to prevent CPU, RAM, or GPU exhaustion.
7. Treat source provenance and session ownership as security boundaries.
8. Keep server-controlled service hosts, models, thresholds, and filesystem
   paths out of client request contracts.

## Initial backend foundation

The first backend milestone provides:

- a FastAPI application factory with CORS and managed startup/shutdown;
- environment-driven Pydantic settings and a safe production-secret check;
- Motor-backed MongoDB initialization and required collection indexes;
- a managed connection to the existing Weaviate instance;
- user registration and OAuth2 password login;
- bcrypt password hashing, short-lived access JWTs, and rotated refresh JWTs;
- authenticated SSE chat at `POST /api/v1/chat/stream`;
- `metadata`, `delta`, and `done` SSE event contracts;
- normalized citation objects suitable for a frontend accordion;
- MongoDB persistence of sessions, user messages, assistant messages, and
  citations;
- authenticated session list, detail, and deletion endpoints;
- strict cross-user session isolation;
- native WSL setup instructions and Docker Compose services.

## API contract goals

### Authentication

- Normalize email addresses and enforce a unique MongoDB index.
- Never return password hashes.
- Distinguish access and refresh token claims.
- Reject expired, malformed, or wrong-type tokens with a consistent 401.
- Add explicit account disablement and refresh-token revocation before public
  deployment.

### Streaming chat

- Accept only a message and optional session ID from the browser.
- Resolve the authenticated user exclusively from the access token.
- Validate session ownership before persisting a message.
- Retrieve and rerank before emitting source metadata.
- Emit one JSON object per SSE event with no raw multiline payloads.
- Persist the complete assistant response with the same citation structure sent
  to the client.
- Return the exact grounded abstention response when context is insufficient.
- Never leak internal exceptions or local configuration in an SSE error event.

### Citation contract

Every citation should expose:

- `document_id` and a human-readable `title`;
- `source_url` or `file_path`;
- the retrieved `chunk_text`;
- hybrid and/or rerank relevance;
- page number and section when available.

Chunk IDs, page ranges, clause numbers, breadcrumbs, and source provenance must
survive ingestion, Weaviate retrieval, API normalization, MongoDB persistence,
and history replay.

### History

- List only sessions owned by the authenticated user, newest first.
- Return messages in timestamp order with original citations.
- Delete the selected session and its messages without affecting other users.
- Add pagination before unbounded production use.

## Dual-chat milestone

The current application now provides two authenticated chat modes with shared
history, rendering, feedback, and source contracts:

- Document Chat uses the existing Weaviate-backed RAG pipeline and emits brief,
  structured citations.
- General Chat uses the local Ollama model without Weaviate and can optionally
  use Ollama web search and fetch when RAG_OLLAMA_API_KEY is configured.
- Chat sessions are separated by mode while sharing the same MongoDB ownership
  and persistence rules.
- Assistant responses support regeneration, version browsing, and feedback in a
  separate MongoDB collection.
- The frontend keeps active streams running while the user browses other chats
  and restores buffered output when they return.
- Shared rendering covers inline citations, source accordions, code blocks,
  highlighting, feedback controls, and smart scrolling.

Operational follow-ups are to validate Ollama web tools with a user-provided API
key and correct the current MongoDB Atlas credentials before cloud-backed tests.

## Production hardening roadmap

### Phase 1: reliability and security

- Add complete API tests with fake MongoDB and RAG dependencies.
- Add rate limiting for registration, login, refresh, and chat.
- Add refresh-token revocation or rotation state in MongoDB.
- Add password reset and verified-email workflows if external email is allowed.
- Add request IDs, structured logs, safe audit events, and latency metrics.
- Add trusted proxy, host, HTTPS, and security-header configuration.
- Add graceful shutdown behavior for active streams and model workers.
- Define retention and privacy policies for chat content.
- Run MongoDB with authentication and secrets outside source control.

### Phase 2: jobs and document management

- Add authenticated document upload, inspection, approval, ingestion, and
  deletion endpoints.
- Move expensive ingestion and evaluation into a durable global worker queue.
- Track job state, progress, cancellation, results, and retention in MongoDB.
- Store uploads in an approved object or file store, not arbitrary client paths.
- Add document ownership, sharing, and collection-level access control.
- Preserve the existing human review gate for golden-set mutation.

### Phase 3: retrieval and answer quality

- Add tenant and document access filters to every Weaviate query.
- Validate generated citations against the exact supplied chunks.
- Add query rewriting only after measuring the frozen regression baseline.
- Add parent-child retrieval and multi-document filters.
- Track Recall@k, MRR, NDCG, abstention precision/recall, latency, and resources.
- Add feedback capture linked to immutable model and retrieval configuration.

### Phase 4: product capabilities

- Add session rename, archive, search, and pagination.
- Add citation-preserving follow-up conversations.
- Add teams, roles, document sharing, and administrative audit views.
- Add quotas and concurrency policies for multi-user deployments.
- Add export and deletion workflows for user-owned data.
- Add deployment profiles for one local machine and distributed infrastructure.

## Testing goals

- Unit-test settings, password hashing, JWT type/expiry, citation normalization,
  and SSE framing.
- API-test registration, login, refresh, protected routes, validation, and
  consistent error responses.
- Test session creation, continuation, ordering, deletion, and cross-user denial.
- Test successful, irrelevant, failed, and disconnected chat streams.
- Keep existing parser, reranker, cache, dashboard, and review tests passing.
- Run live MongoDB, Weaviate, Ollama, and model tests separately from unit tests.

## Definition of done for backend changes

A backend change is complete only when:

- public request and response contracts are typed and documented;
- authentication and ownership checks are explicit;
- blocking work does not run directly on the event loop;
- external clients have bounded lifecycle and safe failure behavior;
- messages and citations are persisted consistently;
- focused tests and the relevant regression suite pass;
- no secret, generated artifact, model file, or private content enters Git;
- any skipped service-backed verification is reported clearly.
