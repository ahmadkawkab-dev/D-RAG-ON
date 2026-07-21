"""
align_golden_dataset.py
========================
Hand-authored eval examples (golden_dataset.jsonl) reference source text
directly, but their `relevant_chunk_ids` are placeholders -- they don't
know what chunk_id your actual parse.py run assigned to that text, since
chunking boundaries depend on your PipelineConfig (max_tokens/overlap).

This script closes that gap: for each golden example, it finds the real
chunk in chunks.jsonl (parse.py's output) whose text best contains/matches
the example's source_text, and rewrites relevant_chunk_ids to the real
chunk_id. Run this once, right after ingesting the source PDF(s) with
--save-jsonl, before running eval.py against the golden set.

Matches below a similarity threshold are left unresolved and flagged --
these need a manual look (the safeguard may have landed in a different
chunk than expected, or split across two).

Usage:
    python align_golden_dataset.py golden_dataset.jsonl chunks.jsonl -o golden_dataset.aligned.jsonl
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
from pathlib import Path

logger = logging.getLogger("align_golden_dataset")


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _partial_ratio(needle: str, text: str) -> float:
    """Containment-oriented similarity, robust to `text` being much longer
    than `needle`.

    plain SequenceMatcher(needle, text).ratio() is 2*M / (len(needle) +
    len(text)) -- that denominator includes the *whole chunk*, so a
    one-sentence source_text excerpt matched against a multi-sentence
    chunk gets punished for the chunk having more text around it, even
    when the excerpt is a perfect (but non-exact, e.g. differing
    whitespace/hyphenation from PDF extraction) match. That's exactly
    this script's main case: golden_dataset.jsonl's source_text is a
    short quoted sentence, chunks.jsonl's chunks are up to ~400 tokens.
    This instead scores what fraction of `needle` is accounted for by
    matching runs found anywhere in `text`, so length of the surrounding
    chunk no longer dilutes the score.
    """
    matcher = difflib.SequenceMatcher(None, needle, text, autojunk=False)
    matched_chars = sum(block.size for block in matcher.get_matching_blocks())
    return matched_chars / max(len(needle), 1)


# Compare a saved source passage with every current chunk and keep the closest one.

def best_match(source_text: str, chunks: list[dict]) -> tuple[str | None, float]:
    """
    Finds the chunk whose text best matches source_text, either by direct
    substring containment (strong signal -- the excerpt is verbatim in the
    chunk) or by partial-ratio similarity as a fallback for near-matches
    (e.g. whitespace/formatting differences from PDF extraction).
    """
    needle = " ".join(source_text.split())  # normalize whitespace
    best_id, best_score = None, 0.0

    for chunk in chunks:
        text = " ".join(chunk.get("text", "").split())
        metadata = chunk.get("metadata", {})
        chunk_id = metadata.get("chunk_id") if isinstance(metadata, dict) else None
        if chunk_id is None or not text:
            continue

        if needle in text:
            return chunk_id, 1.0  # exact substring, no need to keep searching

        score = _partial_ratio(needle, text)
        if score > best_score:
            best_id, best_score = chunk_id, score

    return best_id, best_score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("golden_dataset", type=Path, help="golden_dataset.jsonl with placeholder chunk_ids")
    parser.add_argument("chunks", type=Path, help="chunks.jsonl produced by parse.py (--save-jsonl output)")
    parser.add_argument("-o", "--output", type=Path, default=Path("golden_dataset.aligned.jsonl"))
    parser.add_argument("--threshold", type=float, default=0.6,
                         help="Minimum similarity ratio to accept a fuzzy (non-exact) match")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                         format="%(levelname)-7s | %(message)s")

    examples = load_jsonl(args.golden_dataset)
    chunks = load_jsonl(args.chunks)
    if not examples or not chunks:
        raise SystemExit("Empty golden dataset or chunks file -- nothing to align.")

    resolved, unresolved = 0, 0
    with args.output.open("w", encoding="utf-8") as out:
        for ex in examples:
            source_text = ex.get("source_text", "")
            chunk_id, score = best_match(source_text, chunks) if source_text else (None, 0.0)

            if chunk_id is not None and score >= args.threshold:
                ex["relevant_chunk_ids"] = [chunk_id]
                ex["_alignment_score"] = round(score, 3)
                resolved += 1
            else:
                ex["_alignment_score"] = round(score, 3)
                ex["_alignment_status"] = "UNRESOLVED -- check manually"
                unresolved += 1
                logger.warning("Low-confidence match (%.2f) for: %s", score, ex["query"][:80])

            out.write(json.dumps(ex) + "\n")

    logger.info("Aligned %d/%d examples (%d need a manual check). Written to %s",
                resolved, len(examples), unresolved, args.output)


if __name__ == "__main__":
    main()