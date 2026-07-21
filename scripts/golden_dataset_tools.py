"""Audit and safely optimize a verified JSONL golden dataset.

Optimization never invents questions or answers. It aligns existing source excerpts
against the current parser, enriches records for analysis, and quarantines examples
whose source passage cannot be matched confidently.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from scripts.align_golden_dataset import best_match
from parse import PDFChunkingPipeline


_REQUIRED_FIELDS = {
    "query",
    "relevant_chunk_ids",
    "reference_answer",
    "source_text",
    "verified",
    "provenance",
}




# Decide whether a grounded answer is useful enough for human review.

def assess_candidate(question: str, result: dict, existing_records: list[dict]) -> dict:
    """Conservative quality gate for a potential golden-set question."""
    normalized = " ".join(question.lower().split())
    existing = {" ".join(record.get("query", "").lower().split()) for record in existing_records}
    words = question.split()
    top_score = float(result.get("top_relevance_score", 0.0))
    answer = (result.get("answer") or "").strip()
    ranked = result.get("ranked") or []
    top_metadata = ranked[0].get("metadata", {}) if ranked else {}
    chunk_id = top_metadata.get("chunk_id") if isinstance(top_metadata, dict) else None

    reasons = []
    if not result.get("is_relevant"):
        reasons.append("not grounded in the document")
    if top_score < 0.50:
        reasons.append("retrieval confidence is below the golden-candidate threshold")
    if normalized in existing:
        reasons.append("duplicate of an existing golden question")
    if not 6 <= len(words) <= 45:
        reasons.append("question should contain 6-45 words")
    if not answer or answer.startswith("Question irrelevant"):
        reasons.append("no usable grounded reference answer")
    if not chunk_id:
        reasons.append("top passage has no stable chunk ID")

    important_terms = (
        "must", "minimum", "maximum", "require", "why", "how", "what",
        "frequency", "control", "safeguard", "risk", "define",
    )
    important = any(term in normalized for term in important_terms)
    if not important:
        reasons.append("question does not look decision-relevant or conceptually important")

    return {
        "eligible": not reasons,
        "important": important,
        "reasons": reasons,
        "top_relevance_score": round(top_score, 4),
        "chunk_id": chunk_id,
    }


def build_candidate(question: str, result: dict) -> dict:
    ranked = result.get("ranked") or []
    top = ranked[0] if ranked else {}
    metadata = top.get("metadata", {}) if isinstance(top.get("metadata", {}), dict) else {}
    return {
        "query": question.strip(),
        "relevant_chunk_ids": [metadata["chunk_id"]],
        "reference_answer": (result.get("answer") or "").strip(),
        "source_text": top.get("text", ""),
        "verified": False,
        "provenance": "ui-generated-candidate",
        "_candidate": {
            "top_relevance_score": result.get("top_relevance_score"),
            "created_at": __import__("time").time(),
            "requires_human_review": True,
        },
    }


def append_unique_record(path: Path, record: dict) -> bool:
    records = load_jsonl(path)
    normalized = " ".join(record.get("query", "").lower().split())
    if normalized in {" ".join(row.get("query", "").lower().split()) for row in records}:
        return False
    records.append(record)
    write_jsonl(path, records)
    return True


# Promotion is explicit so generated records never enter the golden set automatically.

def promote_candidate(
    candidates_path: Path,
    index: int,
    golden_path: Path,
    reference_answer: str,
    source_text: str,
) -> bool:
    candidates = load_jsonl(candidates_path)
    if index < 0 or index >= len(candidates):
        return False
    record = dict(candidates[index])
    record["reference_answer"] = reference_answer.strip()
    record["source_text"] = source_text.strip()
    record["verified"] = True
    record["provenance"] = "human-reviewed-ui"
    record.pop("_candidate", None)
    if not append_unique_record(golden_path, record):
        return False
    del candidates[index]
    write_jsonl(candidates_path, candidates)
    return True

def load_jsonl(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp.replace(path)


def classify_record(record: dict) -> dict:
    query = record.get("query", "").lower()
    chunk_id = (record.get("relevant_chunk_ids") or ["unknown"])[0]
    control_match = re.search(r"control(\d{2})", chunk_id)
    if "safeguard" in chunk_id:
        scope = "safeguard"
    elif "overview" in chunk_id:
        scope = "control overview"
    elif chunk_id.startswith("glossary"):
        scope = "glossary"
    elif chunk_id.startswith("intro"):
        scope = "introduction"
    else:
        scope = "other"

    if query.startswith(("how many", "how frequently", "what is the minimum", "what is the maximum")):
        answer_type = "numeric / threshold"
    elif query.startswith(("what are", "what two", "what four")):
        answer_type = "list"
    elif query.startswith(("how do", "what characterizes", "what data")):
        answer_type = "explanation"
    else:
        answer_type = "fact"

    return {
        "scope": scope,
        "control": int(control_match.group(1)) if control_match else None,
        "answer_type": answer_type,
    }


# Report duplicates, verification state, and control coverage for the dataset.

def audit_dataset(records: list[dict]) -> dict:
    questions = [" ".join(r.get("query", "").lower().split()) for r in records]
    ids = [cid for r in records for cid in r.get("relevant_chunk_ids", [])]
    classifications = [r.get("_eval") or classify_record(r) for r in records]
    missing = Counter()
    for record in records:
        missing.update(_REQUIRED_FIELDS - record.keys())

    control_counts = Counter(
        str(item["control"]) for item in classifications if item.get("control") is not None
    )
    covered = sorted(int(value) for value in control_counts)
    return {
        "records": len(records),
        "verified": sum(bool(r.get("verified")) for r in records),
        "duplicate_questions": len(questions) - len(set(questions)),
        "unique_relevant_ids": len(set(ids)),
        "missing_fields": dict(missing),
        "scope_counts": dict(Counter(item["scope"] for item in classifications)),
        "answer_type_counts": dict(Counter(item["answer_type"] for item in classifications)),
        "control_counts": dict(sorted(control_counts.items(), key=lambda item: int(item[0]))),
        "covered_controls": covered,
        "missing_controls": [number for number in range(1, 19) if number not in covered],
        "provenance_counts": dict(Counter(r.get("provenance", "unknown") for r in records)),
    }


# Rebuild records against the current chunks and quarantine weak matches.

def optimize_dataset(
    source_path: Path,
    pdf_path: Path,
    output_path: Path,
    threshold: float = 0.8,
) -> tuple[list[dict], list[dict], dict]:
    source_records = load_jsonl(source_path)
    parsed = PDFChunkingPipeline().run(pdf_path)
    chunks = [{"text": chunk.text, "metadata": chunk.metadata.to_json()} for chunk in parsed]

    accepted: list[dict] = []
    rejected: list[dict] = []
    for record in source_records:
        original_ids = list(record.get("relevant_chunk_ids", []))
        matched_id, score = best_match(record.get("source_text", ""), chunks)
        enriched = dict(record)
        enriched["_eval"] = {
            **classify_record(record),
            "alignment_score": round(score, 3),
            "original_relevant_chunk_ids": original_ids,
        }
        if matched_id and score >= threshold:
            enriched["relevant_chunk_ids"] = [matched_id]
            accepted.append(enriched)
        else:
            enriched["_eval"]["rejection_reason"] = "source passage did not align confidently"
            enriched["_eval"]["best_candidate_id"] = matched_id
            rejected.append(enriched)

    write_jsonl(output_path, accepted)
    rejected_path = output_path.with_name(output_path.stem + ".rejected.jsonl")
    write_jsonl(rejected_path, rejected)
    report = {
        "source_records": len(source_records),
        "accepted_records": len(accepted),
        "rejected_records": len(rejected),
        "threshold": threshold,
        "output": str(output_path),
        "rejected_output": str(rejected_path),
        "audit": audit_dataset(accepted),
    }
    report_path = output_path.with_suffix(".audit.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return accepted, rejected, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("dataset", type=Path)

    optimize_parser = subparsers.add_parser("optimize")
    optimize_parser.add_argument("dataset", type=Path)
    optimize_parser.add_argument("pdf", type=Path)
    optimize_parser.add_argument("-o", "--output", type=Path, default=Path("golden_dataset.optimized.jsonl"))
    optimize_parser.add_argument("--threshold", type=float, default=0.8)

    args = parser.parse_args()
    if args.command == "audit":
        print(json.dumps(audit_dataset(load_jsonl(args.dataset)), indent=2))
    else:
        _, _, report = optimize_dataset(args.dataset, args.pdf, args.output, args.threshold)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

