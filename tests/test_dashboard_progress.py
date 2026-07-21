import json
from pathlib import Path

import pytest

from dashboard import (
    _format_bytes,
    _ingest_phases,
    build_background_job_report,
    build_query_output_report,
    detect_progress,
    estimate_job_progress,
)


def _job(command: list[str]) -> dict:
    return {
        "id": "current",
        "kind": "ingest",
        "status": "running",
        "command": command,
        "started_at": 100.0,
    }


def test_format_bytes_for_job_artifacts() -> None:
    assert _format_bytes(0) == "0 B"
    assert _format_bytes(1536) == "1.5 KB"
    assert _format_bytes(2 * 1024 * 1024) == "2.0 MB"


def test_ingest_phase_plan_with_mineru() -> None:
    assert _ingest_phases(["main.py", "ingest", "doc.pdf"]) == ["parse", "embed"]
    assert _ingest_phases(
        ["main.py", "ingest", "doc.pdf", "--mineru-mode", "off"]
    ) == ["parse", "embed"]
    assert _ingest_phases(
        ["main.py", "ingest", "doc.pdf", "--mineru-mode", "selective"]
    ) == ["parse", "mineru", "embed"]


def test_detect_progress_understands_ingestion_phases() -> None:
    assert detect_progress("INFO [mineru 2/5] page 3") == ("mineru", 2, 5)
    assert detect_progress("INFO [embed 1/2] doc.pdf") == ("embed", 1, 2)


@pytest.mark.parametrize(
    ("log", "expected"),
    [
        ("[parse 1/2]", (1 / 2) / 3),
        ("[mineru 1/4]", (1 + 1 / 4) / 3),
        ("[embed 1/2]", (2 + 1 / 2) / 3),
    ],
)
def test_estimated_ingest_progress_spans_all_phases(
    monkeypatch: pytest.MonkeyPatch, log: str, expected: float
) -> None:
    monkeypatch.setattr("dashboard.time.time", lambda: 200.0)
    job = _job(
        [
            "main.py",
            "ingest",
            "doc.pdf",
            "--mineru-mode",
            "selective",
        ]
    )

    progress, _label = estimate_job_progress(job, log, [job])

    assert progress == pytest.approx(expected)


def test_ingest_run_report_includes_chunk_token_and_artifact_details(
    tmp_path: Path,
) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-test")
    output_dir = tmp_path / "chunks"
    output_dir.mkdir()
    artifact = output_dir / "document.jsonl"
    records = [
        {
            "text": "First chunk text",
            "metadata": {
                "chunk_id": "control01-safeguard1.1",
                "token_count": 42,
                "page_start": 1,
                "page_end": 1,
                "element_type": "clause",
                "clause_number": "1.1",
                "table_annotation": None,
            },
        },
        {
            "text": "Second chunk text",
            "metadata": {
                "chunk_id": "control01-overview",
                "token_count": 68,
                "page_start": 1,
                "page_end": 2,
                "element_type": "narrative",
                "clause_number": None,
                "table_annotation": {"applicable_groups": ["IG1"]},
            },
        },
    ]
    artifact.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    job = {
        "id": "ingest-report",
        "kind": "ingest",
        "status": "completed",
        "started_at": 100.0,
        "finished_at": 110.0,
        "return_code": 0,
        "command": [
            "python",
            "main.py",
            "--collection",
            "DocumentChunks",
            "--embed-model",
            "embeddinggemma",
            "ingest",
            str(source),
            "--max-tokens",
            "400",
            "--overlap-tokens",
            "60",
            "--batch-size",
            "32",
            "--save-jsonl",
            str(output_dir),
            "--mineru-mode",
            "selective",
        ],
    }
    log = (
        "[parse 1/1] document.pdf\n"
        "Produced 2 chunks from 2 pages.\n"
        "MinerU phase finished and memory was released before embedding.\n"
        "[embed 1/1] document.pdf\n"
        "Embedded and upserted 2 chunks from document.pdf\n"
        "Ingest complete: 2 chunks across 1 document(s) into 'DocumentChunks'."
    )

    report = build_background_job_report(job, log)
    saved = report["artifacts"][0]

    assert report["stage_outputs"]["parse"]["output_chunks"] == 2
    assert report["stage_outputs"]["embed_and_upsert"]["chunks_upserted"] == 2
    assert report["stage_outputs"]["mineru"]["memory_released_before_embedding"]
    assert saved["chunks"] == 2
    assert saved["total_tokens"] == 110
    assert saved["minimum_tokens"] == 42
    assert saved["maximum_tokens"] == 68
    assert saved["element_types"] == {"clause": 1, "narrative": 1}




def test_query_report_exposes_each_strategy_output() -> None:
    result = {
        "query": "What does the safeguard require?",
        "ranked": [
            {
                "text": "Maintain an accurate inventory.",
                "score": 0.73,
                "rerank_score": 0.91,
                "metadata": {
                    "chunk_id": "control01-safeguard1.1",
                    "token_count": 42,
                    "page_start": 19,
                    "page_end": 19,
                    "breadcrumb": ["Control 1"],
                    "clause_number": "1.1",
                    "element_type": "clause",
                },
            }
        ],
        "answer": "Maintain an accurate inventory [1].",
        "is_relevant": True,
        "top_relevance_score": 0.91,
        "relevance_threshold": 0.2,
    }
    config = {
        "retrieve_k": 20,
        "alpha": 0.55,
        "embed_model": "embeddinggemma",
        "collection": "DocumentChunks",
        "rerank_model": "Qwen/Qwen3-Reranker-4B",
        "rerank_device": "cuda",
        "answer_enabled": True,
        "answer_model": "qwen3:8b",
    }

    report = build_query_output_report(
        result,
        config,
        ["retrieved 20 candidates"],
        3.25,
    )

    assert report["stage_outputs"]["retrieve"]["retrieved_candidates"] == 20
    assert report["stage_outputs"]["rerank"]["passages_retained"] == 1
    assert report["stage_outputs"]["rerank"]["passages"][0]["token_count"] == 42
    assert report["stage_outputs"]["context_gate"]["is_relevant"] is True
    assert report["stage_outputs"]["answer"]["citation_markers"] == 1

