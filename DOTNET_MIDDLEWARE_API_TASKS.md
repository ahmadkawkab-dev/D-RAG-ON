# Intern Project: .NET Middle-Layer API for RAG System

## Project Goal

Currently, the front-end (UI) talks **directly** to the Python RAG API. We are introducing a **.NET backend**(or any other Framework you prefer) that sits *between* the UI and the Python RAG API.

```
[ UI (React) ]  →  [ .NET Middle-Layer API ]  →  [ Python RAG API ]
                          │
                          ├─ Handles login/signup (Google OAuth)
                          ├─ Stores user accounts
                          ├─ Stores/manages Python RAG API credentials & tokens
                          ├─ Writes audit logs for every request
                          └─ Issues its own session token to the UI
```

**Why:**
- The UI must **never** see or store any credential/token belonging to the Python RAG API. All secrets live only in the .NET backend.
- The UI authenticates against the .NET backend, not the RAG API directly.
- Every action must be traceable via audit logs.

---

## Tech Stack (recommended)

- **.NET 10 Web API** (C#)
- **Entity Framework Core** +  PostgreSQL/MongoDB (either is fine — confirm with team lead)
- **ASP.NET Core Identity** + Google external authentication for OAuth login
- **JWT** for issuing the UI its own session token after login
- **Serilog** (or built-in logging + a dedicated `AuditLog` table) for audit trail
- **.NET Secret Manager** (optional/can use appsettings.json for now) (dev) + **Azure Key Vault / environment variables** (prod) for storing RAG API credentials — never hardcoded, never in `appsettings.json` committed to source control

---

## Phase 0 — Setup

- [ ] 0.1 Create a new **ASP.NET Core Web API** project (`RagMiddleware.Api`).
- [ ] 0.2 Set up solution structure:
  - `RagMiddleware.Api` — controllers, startup/config
  - `RagMiddleware.Application` — business logic, services
  - `RagMiddleware.Domain` — entities (User, AuditLog, etc.)
  - `RagMiddleware.Infrastructure` — EF Core DbContext, RAG API client, external auth
- [ ] 0.3 Set up Git repo, `.gitignore` (ensure `appsettings.Development.json` with secrets is excluded), and branch strategy (feature branches + PR review).
- [ ] 0.4 Confirm with team lead: SQL Server vs PostgreSQL, and get sandbox/dev credentials for the Python RAG API.
- [ ] 0.5 Set up Swagger/OpenAPI for local testing of endpoints.

**Acceptance criteria:** Project builds and runs locally, returns a placeholder `GET /health` → `200 OK`.

---

## Phase 1 — Secure Credential Storage for the RAG API

- [ ] 1.1 Identify every credential/token the Python RAG API currently requires from the UI (API key, bearer token, model access token, etc.) — document them in a short table (name, purpose, where currently stored).
- [ ] 1.2 Store these values in **.NET User Secrets** for local dev (`dotnet user-secrets set ...`) — never in `appsettings.json`.
- [ ] 1.3 For staging/production, store them in **Azure Key Vault** (or environment variables if Key Vault isn't available yet) — document the plan even if actual prod deployment isn't in scope for interns.
- [ ] 1.4 Build a strongly-typed `RagApiOptions` class bound via `IOptions<RagApiOptions>` to read these values — no `Configuration["Key"]` string lookups scattered across the code.
- [ ] 1.5 Confirm: no RAG API secret is ever serialized into any response sent to the UI. Add a code-review checklist item for this.

**Acceptance criteria:** RAG API credentials load from Secret Manager/Key Vault, are injected via DI, and a search of the repo confirms zero hardcoded secrets.

---

## Phase 2 — RAG API Proxy Layer

- [ ] 2.1 Create a `IRagApiClient` interface + `RagApiClient` implementation using `HttpClientFactory` (typed client) to call the Python RAG API.
- [ ] 2.2 Attach the stored credential/token to every outgoing request to the RAG API (e.g. `Authorization` header) inside `RagApiClient` — this is the **only** place that ever touches the RAG API's secret.
- [ ] 2.3 Build .NET endpoints that mirror what the UI needs, e.g.:
  - `POST /api/rag/query` → forwards the question to the Python RAG API, returns the answer
  - `GET /api/rag/documents` → list documents/sources
  - (Add/remove endpoints based on what the current UI actually calls.)
- [ ] 2.4 Ensure the .NET API **never returns** the raw RAG API credential/token in any response body, header, or error message.
- [ ] 2.5 Handle RAG API failures gracefully (timeouts, 4xx/5xx) — return clean, generic error responses to the UI; log full details server-side only.
- [ ] 2.6 Add retry/backoff policy (e.g. Polly) for transient failures when calling the Python RAG API.

**Acceptance criteria:** UI can call `.NET` endpoints and get the same functional result it previously got by calling the Python API directly — but never sees any RAG API secret.

---

## Phase 3 — User Login/Signup via Google OAuth

- [ ] 3.1 Register the app in **Google Cloud Console** (OAuth consent screen + OAuth Client ID/Secret) — get redirect URI approved for local dev (`https://localhost:xxxx/signin-google`).
- [ ] 3.2 Add `Microsoft.AspNetCore.Authentication.Google` package; configure it with the Google Client ID/Secret (stored in Secret Manager/Key Vault — **not** in source).
- [ ] 3.3 Set up **ASP.NET Core Identity** (or a lightweight custom `Users` table if full Identity is overkill — confirm with lead) to persist users.
- [ ] 3.4 Build the auth flow:
  - `GET /api/auth/login/google` → redirects to Google consent screen
  - `GET /api/auth/google/callback` → Google redirects back with user info → create user if new, or fetch existing user by Google account ID/email
  - On success, issue the .NET backend's **own JWT** to the UI (short-lived access token + refresh token strategy recommended)
- [ ] 3.5 Persist on first login: user's Google ID (`sub`), email, display name, avatar URL, created-at timestamp.
- [ ] 3.6 Add `GET /api/auth/me` → returns current logged-in user's profile (from the .NET JWT, not from Google directly).
- [ ] 3.7 Add `POST /api/auth/logout` → invalidate refresh token / session.
- [ ] 3.8 Protect all RAG proxy endpoints (Phase 2) with `[Authorize]` — no anonymous access to `/api/rag/*`.

**Acceptance criteria:** A user can click "Sign in with Google" on the UI, land back logged in, and their user record persists in the DB across sessions. RAG endpoints reject unauthenticated requests with `401`.

---

## Phase 4 — Audit Logging

- [ ] 4.1 Design an `AuditLog` table/entity with fields such as:
  - `Id`, `UserId` (nullable for anonymous/failed attempts), `Action` (e.g. `"RAG_QUERY"`, `"LOGIN_SUCCESS"`, `"LOGIN_FAILED"`), `Endpoint`, `RequestSummary` (no secrets/PII beyond what's needed), `StatusCode`, `IpAddress`, `Timestamp`, `DurationMs`.
- [ ] 4.2 Build an `IAuditLogService` + implementation to write entries to the DB.
- [ ] 4.3 Add middleware (or an action filter) that automatically logs every request to `/api/rag/*` and every auth event (login, logout, signup, failed login).
- [ ] 4.4 Make sure audit logs **never** contain the RAG API credential/token, Google OAuth secret, or full JWT — only high-level metadata.
- [ ] 4.5 Add an admin-only endpoint `GET /api/admin/audit-logs` (paged, filterable by user/date/action) for reviewing logs — protect with a role check (e.g. `Admin` role).
- [ ] 4.6 (Stretch) Add basic retention policy discussion — e.g., how long logs are kept — as a documented decision, even if not implemented.

**Acceptance criteria:** Every login attempt and every RAG query shows up as a row in the audit log table, with no sensitive secrets stored in plain text.

---

## Phase 5 — Hardening & Documentation

- [ ] 5.1 Enable HTTPS-only, configure CORS to only allow the known UI origin(s).
- [ ] 5.2 Add rate limiting on auth and RAG endpoints (e.g. `Microsoft.AspNetCore.RateLimiting`) to prevent abuse.
- [ ] 5.3 Validate/sanitize all inputs on every endpoint (model validation attributes, `[ApiController]` auto-validation).
- [ ] 5.4 Run `dotnet list package --vulnerable` (or equivalent) and resolve any flagged dependency issues.
- [ ] 5.5 Write a short `README.md` covering: architecture diagram, how to run locally, how secrets are configured (without revealing actual values), and how to test the OAuth flow locally.
- [ ] 5.6 Write a short **runbook**: what to do if the Python RAG API is down, how to rotate the RAG API credential, how to revoke a compromised Google OAuth secret.

**Acceptance criteria:** A new intern joining the team could clone the repo, follow the README, and get the whole flow running locally within an hour.

---

## Definition of Done (overall project)

- [ ] UI no longer holds any Python RAG API credential/token anywhere in its code, environment, or browser storage.
- [ ] Users can sign up/log in exclusively via Google OAuth; user records persist in the DB.
- [ ] All RAG queries and auth events are captured in the audit log.
- [ ] All secrets (RAG API credentials, Google OAuth client secret, JWT signing key) are stored outside source control.
- [ ] Endpoints are documented (Swagger) and protected appropriately (`[Authorize]` where needed).
- [ ] README + runbook are complete enough for handoff.

---

## Notes for Interns

- Ask before assuming: if the Python RAG API's auth mechanism (API key vs. bearer token vs. mTLS) isn't documented yet, get that from whoever owns the RAG API before starting Phase 2.
- Don't invent your own crypto/token scheme for the .NET → UI session — use standard JWT + refresh token patterns from ASP.NET Core Identity.
- Commit early, commit often, and open a draft PR per phase so mentors can review incrementally rather than one giant PR at the end.
