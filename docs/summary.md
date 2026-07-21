# RAG Pipeline Summary

## 1. End-to-end flow

`PDF -> parse/layout cleanup -> structure-aware chunks -> passage embeddings -> Weaviate -> hybrid retrieval -> Qwen reranking -> relevance gate -> grounded answer -> evaluation/judging`

The implemented pipeline is fully local: Ollama serves embeddings, answer, and judge models; Hugging Face Transformers runs the reranker; Weaviate stores and searches vectors. The current code uses **PyMuPDF + EmbeddingGemma**. The README/notebook also describes an older teaching baseline using Unstructured + BGE-small, so it should not be treated as the live implementation.

## 2. Parsing and chunking

| Area | Strategy used |
|---|---|
| PDF extraction | PyMuPDF extracts text with page, font, position, and direction metadata. Overlapping/duplicate spans and non-horizontal text are removed. |
| Reading order | Detects column layouts and chooses row-wise or column-wise ordering. Bare safeguard numbers are joined to their following titles. |
| Scanned pages | Optional Tesseract OCR fallback when a page has fewer than 30 extracted characters and contains images. |
| Cleanup | Repeated headers/footers are detected only in page margins and removed when repeated on at least 20% of pages, with a four-page minimum. |
| Structure | Font-size tiers create heading breadcrumbs. Safeguards such as `5.3` form semantic boundaries. CIS table columns recover IG1/IG2/IG3, asset type, and security-function metadata. |
| Chunk splitting | Split by safeguard/clause first; oversized text is split by paragraphs, then sentences, then fixed token windows. Small adjacent pieces are merged when safe. |
| IDs/metadata | Stable semantic IDs such as `control05-safeguard5.3`, with `-partNN` for duplicates; metadata includes source, pages, breadcrumb, clause, element type, and token count. |

Optional MinerU2.5 assistance keeps this PyMuPDF output intact and adds only
validated `mineru_visual_supplement` chunks. Selective mode targets low-text,
image-heavy, CIS summary-table, or manually requested pages; results are cached
per PDF/model/DPI/page. The 1.2B visual model is unloaded before passage
embedding begins.

Frozen parser settings: **400 max tokens**, **40 min tokens**, **60-token overlap**, using `cl100k_base` for counting. The frozen CIS v8 corpus contains **384 unique chunks**, 52,090 tokens total, with 294 clause and 90 narrative chunks.

## 3. Embeddings, storage, and retrieval

- Embedding model: Ollama `embeddinggemma`.
- Asymmetric prompting is used: queries receive a search-query prefix; passages receive a document prefix.
- Passages are embedded in batches of 32 by default.
- Weaviate uses supplied vectors (`Vectorizer.none()`); deterministic UUID5 values make re-ingestion update stable chunk IDs instead of intentionally creating new objects.
- Retrieval is hybrid **BM25 + dense-vector search**, fused with relative-score fusion. Defaults: `retrieve_k=20`, `alpha=0.5`; `alpha=0` is keyword-only and `alpha=1` is vector-only.
- Metadata is currently stored as one JSON string beside `text`; first-class metadata fields and filters are not implemented yet.

## 4. Reranking and answer generation

- Reranker: `Qwen/Qwen3-Reranker-4B`, run locally with Transformers; GPU uses bfloat16 and CPU uses float32.
- It scores each query/passage from the final `yes` versus `no` logits and returns a relevance probability, rather than asking a chat model to invent a score.
- Defaults: rerank 20 retrieved candidates and keep `top_n=5`; scoring batch size is 8.
- The UI/programmatic pipeline applies a relevance gate at **0.20** on the best reranker score. Below it, the exact abstention is: `Question irrelevant to the available document context.` The standalone CLI path does not currently apply this pre-generation gate.
- The answer model defaults to Ollama `qwen2.5:1.5b`. Its prompt permits only supplied context, asks for `[1]`-style citations, and requires abstention when evidence is missing.
- Models are loaded sequentially and explicitly unloaded between stages to reduce CPU/GPU out-of-memory failures.

## 5. Context windows, tokens, and limits

| Stage | Effective limit |
|---|---|
| Chunking | 400 tokens per chunk; 60-token overlap; fragments below 40 tokens are merged where possible. |
| Embedding | Passage input is normally bounded by the 400-token chunk limit. Query length is not explicitly capped in code. |
| Retrieval | 20 candidates by default. |
| Reranker | Hard-coded 8,192-token query/passage prompt limit with longest-first truncation. |
| Generator context | Five chunks by default, so roughly **up to 2,000 chunk tokens**, plus numbering, prompt, and query overhead. `cl100k_base` counts chunks, while the answer model uses its own tokenizer, so this is an estimate. |
| Generator output/window | No explicit `num_ctx`, prompt budget, or maximum output-token setting is enforced; actual limits come from the installed Ollama model/configuration. |
| Judge | No explicit token cap in this project; default request timeout is 900 seconds, three retries, and 30-minute keep-alive. |

Main gap: add tokenizer-aware context packing, duplicate removal, reserved output space, and explicit input/output limits before scaling to more or larger documents.

## 6. Evaluation and judging

Two complementary evaluation layers are used:

1. **Deterministic ID metrics:** Hit@k, Recall@k, and MRR@k compare post-rerank `top_n` chunk IDs with golden relevant IDs. Current code does not separately report pre-rerank metrics or NDCG.
2. **DeepEval with a local judge:** answer relevancy, faithfulness, contextual precision, contextual recall, and contextual relevancy. The default judge is Ollama `qwen3:8b`, temperature 0, thinking disabled, one case at a time, with caching/checkpoints.

LLM judging is useful but can be noisy or self-inconsistent. Prefer a stronger/different judge from the answer model, inspect reasons, and never replace human review of golden questions, answers, sources, and chunk IDs.

## 7. Golden-data files

Each record normally contains `query`, `relevant_chunk_ids`, `reference_answer`, `source_text`, `verified`, and `provenance`.

| File | Purpose |
|---|---|
| `golden_dataset.jsonl` | Source set of 16 verified, source-derived CIS questions. It covers safeguards, control summaries, glossary, and introduction material; its IDs must be aligned whenever chunking changes. |
| `golden_dataset.aligned.jsonl` | Older 16-record alignment against a previous chunk set, mainly using numbered chunk IDs. Four control-summary questions remained unresolved. Keep only for historical comparison. |
| `golden_dataset.current.aligned.jsonl` | Alignment of all 16 records to the current semantic-ID chunk set. Four low-confidence overview/table questions are still marked unresolved, so it is not the safest regression set. |
| `golden_dataset.optimized.jsonl` | Recommended current smoke/regression set: 12 verified records accepted at alignment score >= 0.80, with audit metadata. It covers Controls 4, 5, 8, and 11 plus introduction and glossary content. |
| `golden_dataset.optimized.rejected.jsonl` | Quarantine containing four low-confidence control-summary/IG-count questions for Controls 13, 18, 16, and 14. Do not score with them until source alignment is corrected and reviewed. |
| `golden_dataset.optimized.audit.json` | Audit report for the optimized split: counts, coverage, answer types, provenance, missing controls, and rejection totals. |
| `golden_dataset_3.jsonl` | Three-question fast smoke subset covering Safeguards 5.3, 8.10, and 4.3; it matches the small run recorded in `eval_results.json`. |

The frozen benchmark manifest currently registers **no golden dataset**, and human semantic review is still marked pending. The 12-question optimized set is too narrow for broad quality claims.

## 8. Tuning priorities

- Freeze a development/regression set and keep a separate untouched holdout; expand toward at least 90 reviewed questions, plus unrelated/abstention and multi-passage cases.
- Sweep `retrieve_k`, hybrid `alpha`, `top_n`, relevance threshold, chunk size/overlap, and model choices on the same frozen corpus and seeded sample.
- Measure retrieval both before and after reranking with Recall@k, MRR, and NDCG; also track abstention precision/recall, faithfulness, latency, memory, and per-stage failures.
- Re-ingest the frozen 384-chunk corpus before trusting scores: existing evaluation output shows duplicate passages and some missing chunk IDs, consistent with a stale/mixed Weaviate collection.
- Add citation validation, first-class metadata filters, parent-child retrieval, context deduplication, model/config hashes, and stage-level timing before adding query rewriting or more complex agents.

## 9. Practical quality rule

Treat the pipeline as versioned data: any change to the PDF, parser, chunk settings, chunk IDs, embedding model, or collection requires re-parsing/re-ingestion, golden re-alignment, benchmark-version update, and regression evaluation.
