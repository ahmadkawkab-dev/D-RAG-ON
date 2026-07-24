# Dual Chat Integration

## Scope

The application exposes two intentionally separate chat modes behind one
authenticated FastAPI API and one shared React response renderer.

- General Chat is open-domain conversation using local Qwen3 8B.
- Document Chat is grounded RAG using Weaviate retrieval, relevance gating,
  concise citations, and the existing local answer model.
- MongoDB stores users, sessions, messages, response versions, citations, and
  feedback.
- Weaviate remains document retrieval storage only.

General Chat never queries Weaviate. Document Chat never invokes web tools.

## Backend endpoints

All routes require an access-token bearer header except registration, login,
refresh, and health.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | /api/v1/general/stream | General Chat SSE |
| POST | /api/v1/chat/stream | Document Chat SSE |
| GET | /api/v1/history/sessions?mode=general | General sessions |
| GET | /api/v1/history/sessions?mode=document | Document sessions |
| GET | /api/v1/history/sessions/{id} | Messages and feedback |
| DELETE | /api/v1/history/sessions/{id} | Session cascade delete |
| PUT | /api/v1/feedback/messages/{id} | Upsert response feedback |

Both stream endpoints accept:

~~~json
{
  "message": "Question text",
  "session_id": null,
  "regenerate_message_id": null
}
~~~

For regeneration, pass the original user-message ID as
regenerate_message_id. The backend stores a new assistant message with the same
reply_to_message_id and an incremented version; older versions remain
available.

## SSE contract

The event order is started, metadata, zero or more delta events, then done.

~~~text
event: started
data: {"session_id":"...","chat_mode":"document","reply_to_message_id":"...","version":1}

event: metadata
data: {"sources":[...]}

event: delta
data: {"content":"partial answer"}

event: done
data: {"session_id":"...","message_id":"...","reply_to_message_id":"...","version":1}
~~~

Document metadata includes document ID, title, URL or file path, page, section,
chunk ID, breadcrumb, brief summary, chunk text, score, relevance, and retained
metadata. General Chat metadata is empty unless a web tool produced sources.

## General Chat web tools

Local Qwen conversation does not need an API key. Ollama-hosted web search and
fetch require:

~~~dotenv
RAG_OLLAMA_API_KEY=your_key
RAG_GENERAL_WEB_SEARCH_ENABLED=true
RAG_GENERAL_WEB_FETCH_ENABLED=true
RAG_GENERAL_WEB_MAX_RESULTS=5
~~~

When the key is absent, the backend does not expose web tools to the model.
General Chat still works locally. Web results become structured citations and
are never written to Weaviate.

## Frontend layout

- src/features/GeneralChat owns General Chat labels and prompts.
- src/features/DocumentChat owns Document Chat labels and prompts.
- src/api/client.ts is the shared authenticated API and SSE client.
- src/components/ResponseRenderer.tsx renders content, inline citations,
  keyword highlights, fenced code, and source accordions.
- src/components/FeedbackControls.tsx persists feedback.
- src/ConnectedApp.tsx owns session navigation and per-session stream state.

Switching chats or modes does not abort the active fetch. Stream updates are
buffered by session and completed history is refreshed from MongoDB.
Auto-scroll only follows the answer while the reader remains near the bottom;
otherwise a NEW CONTENT control appears.

Prompt/KV behavior, retrieval and answer TTLs, cache invalidation, and the
native-WSL Ollama setup helper are documented in
docs/PROMPT_RETRIEVAL_CACHING.md.

## Start locally

From native Ubuntu WSL:

~~~bash
cd /home/ahmad/rag_setup/rag_setup
uv sync
docker compose up -d mongodb weaviate
uv run uvicorn backend.main:app --reload
~~~

In another native WSL terminal:

~~~bash
cd /home/ahmad/rag_setup/rag_setup/frontend
npm install
npm run dev
~~~

The frontend defaults to http://localhost:8000. Override it with
VITE_API_BASE_URL.

## Verification performed

- Backend unit tests: 13 passed; opt-in live tests are separate.
- Live local MongoDB, Weaviate, Ollama, auth, Document Chat SSE, citation
  persistence, and deletion: passed.
- Live General Chat Qwen3 SSE, history, and feedback: passed.
- TypeScript type-check and production Vite build: passed.
- ESLint: passed.

The current Atlas URI reaches MongoDB Atlas but Atlas returns bad auth. Correct
the username/password or authentication database in .env, then rerun the
MongoDB ping or live suite. Do not commit .env.

Web search/fetch live verification remains pending until RAG_OLLAMA_API_KEY is
configured.
