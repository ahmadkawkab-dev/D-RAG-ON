# Answer Performance and Background Chats

## Behavior

Questions are routed into two execution modes:

- **Fast:** short, single-part questions use hybrid Weaviate retrieval directly, keep Ollama models warm, return at most 160 generated tokens, and enforce a five-second total retrieval-plus-generation budget.
- **Complex:** multi-part, comparison, analysis, evaluation, synthesis, detailed, or long questions use adaptive precision reranking and have a 900-second (15-minute) total budget.

The first SSE event is now `started`:

```text
event: started
data: {"session_id":"...","mode":"fast"}
```

This gives the browser the MongoDB session ID before retrieval begins. The frontend buffers tokens under that session, allowing users to browse another saved chat or open New Chat while the original answer continues. Returning to the running session restores its partial answer. Completion never changes the currently viewed chat.

## Fast deadline fallback

If a cold local model cannot produce a token within the remaining five-second budget, the API returns a concise excerpt from the strongest retrieved source with an inline `[1]` citation. The response remains grounded and is persisted normally.

Identical questions over identical retrieved context are held in an in-process LRU cache. A backend restart clears this cache.

## Brief citations

The LLM is instructed to cite only the strongest supporting sources inline and not generate a separate source list. The frontend still receives full structured citation metadata for persistence, but accordion cards display only the first 220 normalized characters of each chunk.

## Configuration

All names use the `RAG_` prefix when configured through `.env`:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `FAST_RETRIEVE_K` | `8` | Fast-path Weaviate candidates |
| `FAST_TOP_N` | `3` | Fast-path context and citation count |
| `FAST_QUERY_MAX_WORDS` | `24` | Length threshold before complex routing |
| `FAST_ANSWER_MAX_TOKENS` | `160` | Concise fast response cap |
| `FAST_ANSWER_TIMEOUT_SECONDS` | `5` | Total fast retrieval/generation budget |
| `COMPLEX_ANSWER_MAX_TOKENS` | `640` | Complex response cap |
| `COMPLEX_ANSWER_TIMEOUT_SECONDS` | `900` | Total complex budget (15 minutes) |
| `ANSWER_KEEP_ALIVE` | `30m` | Ollama model residency |
| `ANSWER_CONTEXT_CHARS_PER_CHUNK` | `1800` | Prompt context cap per source |
| `ANSWER_CACHE_SIZE` | `128` | In-memory completed-answer entries |

## Measured local results

On the current WSL workstation (RTX 3070 Laptop GPU, 8 GB):

- True cold fast request: **4.911 seconds** total.
- Warm uncached fast request: **1.271 seconds** total.
- Warm cached repeat: **0.200 seconds** total.
- Complex precision request: **99.654 seconds** total.

Run the repeatable benchmark from native WSL:

```bash
cd /home/ahmad/rag_setup/rag_setup
uv run python -m scripts.benchmark_answer_latency --cold --runs 2
```

Pass a quoted question to benchmark complex routing.

## Operational notes

- Fast questions avoid loading either Hugging Face reranker.
- Complex questions unload warm Ollama models before precision reranking to protect the 8 GB GPU, then reload the answer model.
- Generation uses Ollama's asynchronous stream, so browser disconnects are cancellable without waiting on a non-cancellable worker thread.
- Requests remain serialized at the model boundary to prevent GPU memory contention; browsing and history APIs remain responsive while generation continues.
