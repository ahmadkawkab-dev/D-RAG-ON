# Prompt, KV, and Retrieval Caching

## What is implemented

The FastAPI process owns three bounded TTL/LRU caches:

| Cache | Default TTL | Default size | Cache input |
| --- | ---: | ---: | --- |
| Document retrieval | 5 minutes | 256 | Query, corpus revision, collection, models, and retrieval settings |
| Grounded answer | 15 minutes | 128 | Prompt version, answer model, context size, question, and exact evidence |
| Web retrieval | 2 minutes | 128 | Tool name, arguments, result limit, and fetch policy |

Cached values are copied before reuse so one request cannot mutate a later
request. Timed-out or partial model answers are never cached. Cache objects are
application-scoped, process-local, bounded, and cleared by an API restart.

Document Chat can safely share retrieval entries because the current Weaviate
collection is a shared document library. When tenant/document access filters
are introduced, their authorization scope must be added to the retrieval cache
key before caching filtered results.

## Invalidation

After changing or reingesting the Weaviate corpus, change this value in `.env`
to invalidate every earlier document-retrieval key immediately:

~~~dotenv
RAG_RETRIEVAL_CACHE_REVISION=v2
~~~

Normal entries also expire after their TTL. Changing model IDs, prompt version,
retrieval limits, alpha, threshold, or evidence automatically changes the key.

Useful overrides:

~~~dotenv
RAG_RETRIEVAL_CACHE_SIZE=256
RAG_RETRIEVAL_CACHE_TTL_SECONDS=300
RAG_ANSWER_CACHE_SIZE=128
RAG_ANSWER_CACHE_TTL_SECONDS=900
RAG_GENERAL_WEB_CACHE_SIZE=128
RAG_GENERAL_WEB_CACHE_TTL_SECONDS=120
RAG_ANSWER_NUM_CTX=8192
RAG_GENERAL_CHAT_NUM_CTX=8192
RAG_ANSWER_KEEP_ALIVE=30m
RAG_GENERAL_CHAT_KEEP_ALIVE=30m
~~~

Set a cache size to zero to disable that application cache.

## Ollama KV cache

The prompts now put stable instructions in a system message and keep models
resident, allowing Ollama to reuse its local runtime and KV state where
supported. Ollama does not expose API prompt-cache IDs, and its Anthropic
compatibility endpoint does not support `cache_control` prefix blocks. The
backend therefore does not fake cross-session KV handles or reuse hidden
conversation state.

For this Windows Ollama plus native WSL setup, configure the server once from
Ubuntu WSL:

~~~bash
cd /home/ahmad/rag_setup/rag_setup
bash scripts/configure_ollama_kv_cache.sh
~~~

The helper permits two resident models so the embedding model does not evict
the grounded-answer model before generation. Parallelism remains one to keep
context memory bounded on the current 8 GB GPU. General Chat may still replace
one of those models when switching chat modes.

Then quit and restart Ollama Desktop. The helper enables Flash Attention and
keeps the KV cache at `f16`, Ollama's high-precision default. This favors answer
quality. `q8_0` can reduce cache memory, but it introduces a small precision
tradeoff and should only be enabled after measuring answer quality.

KV caching improves prompt processing latency and memory behavior; it does not
make answers intrinsically more accurate. The larger 8K context, preserved
conversation history, evidence-aware keys, and retrieval freshness controls
are the quality-related parts of this change.

Complex document queries may unload Ollama models before GPU-heavy reranking to
avoid exhausting an 8 GB GPU. Ordinary queries retain the warm model and cache.
