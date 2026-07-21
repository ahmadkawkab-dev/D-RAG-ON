# Frozen CIS Controls benchmark corpus v1

- Benchmark version: `cis-controls-v8-v1`
- Chunk-set version: `cis-controls-v8-v1-f3ee33dc43a8`
- Chunk SHA-256: `f3ee33dc43a825e2b0d72133e0cf53491c9473ad4ffdeb95163c93ffae40a159`
- Source PDF SHA-256: `54d43a1933f9f302841ccc2ca8fb863393d9a34ac16a5e136ad0beea2b58e0f0`
- Chunks: 384 with 384 unique IDs
- Human semantic review: pending

Verify integrity before and after every benchmark editing session:

```bash
uv run python -m scripts.benchmark_freeze verify benchmark/cis-controls-v8-v1/manifest.json
```

Reproduce chunks without changing any parser option:

```bash
uv run python parse.py \
  data/CIS_Controls__v8__Critical_Security_Controls__2023_08.pdf \
  --parser-config benchmark/cis-controls-v8-v1/parser_config.json \
  -o reproduced_chunks.jsonl
```

Re-ingest this benchmark corpus:

```bash
uv run python main.py ingest \
  data/CIS_Controls__v8__Critical_Security_Controls__2023_08.pdf \
  --parser-config benchmark/cis-controls-v8-v1/parser_config.json \
  --batch-size 32 --save-jsonl chunks
```

Do not modify `parser_config.json`, the source PDF, `parse.py`, or the recorded chunks while building the 90-question benchmark. Any intentional change starts a new benchmark version, such as `cis-controls-v8-v2`, followed by re-alignment and human review.

See `HUMAN_REVIEW.md` for the work that must remain human.
