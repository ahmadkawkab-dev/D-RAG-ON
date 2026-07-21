"""Decision helpers for the adaptive reranking path.

The lightweight reranker handles clear retrieval results. The larger reranker is
reserved for relevant results that are ambiguous or for questions that need
evidence from multiple parts of the corpus.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

DEFAULT_LIGHT_RERANKER = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_HEAVY_RERANKER = "Qwen/Qwen3-Reranker-4B"

_CLAUSE_REFERENCE = re.compile(
    r"(?:(?:control|safeguard)\s+)?(?P<number>\d+(?:\.\d+)+)",
    re.IGNORECASE,
)
_COMPLEX_QUERY_MARKERS = re.compile(
    r"\b(compare|comparison|contrast|difference|different|versus|vs\.?|"
    r"across|relationship|combined|multiple|summarize|synthesi[sz]e)\b",
    re.IGNORECASE,
)


def _normalise_text(value: Any) -> str:
    """Return stable text for duplicate checks without changing source chunks."""

    return " ".join(str(value or "").lower().split())


def exact_clause_matches(
    query: str,
    candidates: Iterable[dict[str, Any]],
    *,
    minimum_hybrid_score: float = 0.70,
) -> list[dict[str, Any]]:
    """Find high-confidence passages matching a clause named in the query."""

    clause_refs = _referenced_clauses(query)
    if not clause_refs:
        return []

    matches = [
        candidate
        for candidate in deduplicate_candidates(candidates)
        if clause_refs.intersection(_candidate_clauses(candidate))
    ]
    if not matches or float(matches[0].get("score", 0.0)) < minimum_hybrid_score:
        return []
    return matches


def deduplicate_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first copy of each retrieved passage.

    Some indexes contain the same passage under different chunk IDs. Scoring
    those copies wastes reranker time and can crowd useful evidence out of the
    final context.
    """

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, candidate in enumerate(candidates):
        text_key = _normalise_text(candidate.get("text"))
        key = text_key or f"chunk:{candidate.get('chunk_id', index)}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    return unique


def _referenced_clauses(query: str) -> set[str]:
    return {match.group("number") for match in _CLAUSE_REFERENCE.finditer(query)}


def _candidate_clauses(candidate: dict[str, Any]) -> set[str]:
    """Read clause IDs from metadata, with passage text as a safe fallback."""

    metadata = candidate.get("metadata") or {}
    values = {
        str(candidate.get("clause_number") or "").strip(),
        str(metadata.get("clause_number") or "").strip(),
        str(metadata.get("clause") or "").strip(),
    }
    text = str(candidate.get("text") or "")
    values.update(_referenced_clauses(text[:240]))
    return {value for value in values if value}


def choose_rerank_route(
    query: str,
    ranked: list[dict[str, Any]],
    *,
    relevance_floor: float = 0.20,
    confidence_threshold: float = 0.80,
    margin_threshold: float = 0.10,
) -> dict[str, Any]:
    """Choose whether the lightweight result is enough or needs escalation."""

    top_score = float(ranked[0].get("rerank_score", 0.0)) if ranked else 0.0
    second_score = (
        float(ranked[1].get("rerank_score", 0.0)) if len(ranked) > 1 else 0.0
    )
    margin = top_score - second_score

    clause_refs = _referenced_clauses(query)
    exact_clause_match = bool(
        ranked and clause_refs.intersection(_candidate_clauses(ranked[0]))
    )
    complex_query = bool(_COMPLEX_QUERY_MARKERS.search(query))

    if not ranked or top_score < relevance_floor:
        route = "reject"
        reason = "lightweight reranker found no sufficiently relevant evidence"
    elif exact_clause_match:
        route = "light"
        reason = "top result matches the clause explicitly named in the question"
    elif complex_query:
        route = "heavy"
        reason = "question appears to require comparison or evidence synthesis"
    elif top_score >= confidence_threshold and margin >= margin_threshold:
        route = "light"
        reason = "lightweight reranker has a confident, clearly separated top result"
    else:
        route = "heavy"
        reason = "retrieval is relevant but the lightweight ranking is uncertain"

    return {
        "route": route,
        "reason": reason,
        "top_score": top_score,
        "margin": margin,
        "exact_clause_match": exact_clause_match,
        "complex_query": complex_query,
    }

