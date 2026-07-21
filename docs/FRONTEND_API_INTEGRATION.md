# Frontend API Integration

## Scope

The React frontend is connected to the FastAPI backend without changing the existing visual direction. Authentication, chat streaming, citations, and MongoDB-backed history are functional; broader UI/UX work can continue independently in the design-focused frontend project.

## Runtime topology

- Frontend: Vite on `http://localhost:5173`
- Backend: FastAPI on `http://localhost:8000`
- API prefix: `/api/v1`
- Browser API setting: `VITE_API_BASE_URL`
- Backend CORS must include the exact frontend origin.

Always run project commands from native WSL:

```bash
cd /home/ahmad/rag_setup/rag_setup
```

## Local configuration

Copy the frontend-only example if the backend is not on the default origin:

```bash
cd frontend
cp .env.example .env.local
```

`frontend/.env.local` may contain only browser-safe values. Never put MongoDB credentials, JWT signing keys, Weaviate credentials, or other secrets in a `VITE_*` variable because Vite embeds them in the browser bundle.

## Start the applications

In terminal one:

```bash
cd /home/ahmad/rag_setup/rag_setup
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In terminal two:

```bash
cd /home/ahmad/rag_setup/rag_setup/frontend
npm run dev
```

Open `http://localhost:5173`.

## Implemented flows

### Authentication

1. Register sends JSON to `POST /api/v1/auth/register`.
2. Login uses the OAuth2 form contract at `POST /api/v1/auth/login`.
3. Authenticated requests send `Authorization: Bearer <access_token>`.
4. A `401` triggers one refresh through `POST /api/v1/auth/refresh`, then retries the original request once.
5. A failed refresh clears the local session and returns the user to sign-in.

The current backend returns tokens in JSON rather than secure cookies, so the frontend stores them in `localStorage`. For a public production deployment, prefer short-lived access tokens plus an `HttpOnly`, `Secure`, `SameSite` refresh-token cookie and add CSP/XSS hardening.

### Streaming chat

`POST /api/v1/chat/stream` uses `fetch()` instead of `EventSource` because the endpoint requires a POST body and bearer token. The client incrementally parses SSE boundaries even when a frame is split across network chunks.

Handled events:

- `metadata`: attaches structured sources to the pending assistant response.
- `delta`: appends each LLM token immediately.
- `done`: captures the server session ID, then reloads canonical messages and sessions from MongoDB.
- `error`: stops the pending state and surfaces the backend-safe error message.

### History and citations

- Session list: `GET /api/v1/history/sessions`
- Session messages: `GET /api/v1/history/sessions/{session_id}`
- Session deletion: `DELETE /api/v1/history/sessions/{session_id}`
- Sidebar search filters already-loaded session titles locally.
- Assistant sources render in native `<details>` accordions with title, page/section, confidence, chunk text, and a safe HTTP(S) link or file path.

## Frontend modules

- `src/api/types.ts`: API contract types.
- `src/api/client.ts`: base URL, JWT lifecycle, REST calls, and SSE parser.
- `src/components/AuthPanel.tsx`: login/register gate.
- `src/components/SourcesAccordion.tsx`: citation rendering.
- `src/components/PixelBot.tsx`: shared existing visual element.
- `src/ConnectedApp.tsx`: session state and API orchestration.

The original `src/App.tsx` remains untouched as a design reference. `src/main.tsx` mounts `ConnectedApp.tsx`.

## Verification

```bash
cd /home/ahmad/rag_setup/rag_setup/frontend
npm run lint
npm run build
```

Manual acceptance checklist:

1. Register or sign in.
2. Send a prompt and confirm tokens appear progressively.
3. Expand sources and inspect citation metadata.
4. Reload the page and reopen the saved session.
5. Delete the session and confirm it disappears.
6. Let an access token expire and confirm refresh occurs without interrupting the user.

## Known UI placeholders

Document upload, Help Center, and Settings remain visual placeholders. They are intentionally outside this API-integration feature and can be designed and implemented later.
