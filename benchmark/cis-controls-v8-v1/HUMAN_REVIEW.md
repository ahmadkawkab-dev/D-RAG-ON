# Human benchmark review checklist

Corpus contract: `cis-controls-v8-v1-f3ee33dc43a8`

Do not edit the frozen PDF, parser configuration, parser source, or chunks file while constructing this benchmark. Run `uv run python -m scripts.benchmark_freeze verify benchmark/cis-controls-v8-v1/manifest.json` before and after every review session.

## Review each proposed question

- [ ] The question is important enough to detect a meaningful RAG regression.
- [ ] The wording is unambiguous and does not reveal the answer.
- [ ] The reference answer is concise, complete, and factually correct.
- [ ] Every claim in the answer is supported by the recorded source passage.
- [ ] The relevant chunk ID exists in the frozen chunks file.
- [ ] All necessary chunk IDs are included for multi-passage questions.
- [ ] The question is not a semantic duplicate of an existing benchmark question.
- [ ] The difficulty and question-type labels are appropriate.
- [ ] No outside knowledge is required.
- [ ] A second reasonable interpretation would not be unfairly marked wrong.

Only after completing these checks should `verified` become `true` and provenance become `human-reviewed-ui` or another clearly human-review label.

## Coverage target

Approve five questions per Control across Controls 1-18. Within each control, prefer one purpose question, one exact safeguard requirement, one threshold or cadence question, one scope/comparison question, and one applied or multi-passage question.

Keep development, regression, and holdout splits separate. Do not inspect the holdout set while tuning retrieval or prompts.

## Human-only completion

When all 90 questions have been reviewed, fill the `human_review` object in `manifest.json` with reviewer, timestamp, and notes. This must not be automated.
