# RAG improvement roadmap

## Current baseline

The pipeline now has hybrid retrieval, Qwen3 reranking, grounded generation, resilient local judging, unique chunk IDs, background jobs, telemetry, and a reviewed golden-candidate workflow.

The optimized set contains 12 verified aligned questions. It is useful for smoke tests, but covers only Controls 4, 5, 8, and 11 plus introduction and glossary content.

## Highest-value next steps

1. Re-ingest the PDF so Weaviate contains the corrected unique IDs.
2. Expand to at least 90 verified questions: five per CIS Control.
3. Split data into development, regression, and untouched holdout sets.
4. Add 10-15 unrelated questions with the exact expected abstention response.
5. Add multi-passage questions that require evidence from two chunks.
6. Measure latency and resources separately for retrieval, reranking, generation, and judging.

## Retrieval quality

- Sweep retrieve_k, alpha, top_n, and the relevance threshold on the frozen regression set.
- Store control, safeguard, pages, document, and section as first-class Weaviate properties.
- Add filters for document, control, implementation group, and page.
- Consider parent-child retrieval: search small passages, return their larger section.
- Add query rewriting only after the baseline is measured.
- Cache query embeddings and reranker scores using the model and chunk-set hash.

## Generation and safety

- Return structured citations with chunk ID and page number.
- Validate every citation against supplied context.
- Abstain before generation when the relevance gate fails.
- Add prompt-injection tests inside ingested documents.
- Limit context tokens and remove redundant passages.

## Evaluation

- Report retrieval metrics before and after reranking.
- Add Recall@k, MRR, and NDCG for both stages.
- Track abstention precision and recall for unrelated questions.
- Record model digests, parser version, chunk-set hash, run settings, and stage latency.
- Compare changes with the same seeded sample or the full frozen regression set.
- Never auto-verify generated candidates; require review of question, answer, source, and ID.

## Performance and functionality

- Quantize the reranker only after measuring quality impact.
- Lower reranker batch size automatically after CUDA out-of-memory.
- Keep one active model resident, matching the current sequential design.
- Skip unchanged PDFs using document content hashes.
- Add multi-document selectors and access-control filters.
- Add citation-preserving follow-up conversations.
- Open the source PDF page directly from each citation.
- Export HTML/JSON comparisons and schedule regression runs.
