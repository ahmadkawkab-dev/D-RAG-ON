import json
from pathlib import Path

import fitz
from streamlit.testing.v1 import AppTest

import parse as parser_core
from parse import PipelineConfig
from parsing_workspace import (
    build_chunk_output_manifest,
    chunk_table_rows,
    chunks_to_jsonl,
    filter_chunk_records,
    inspect_pdf_bytes,
    pipeline_config_from_payload,
    pipeline_config_payload,
    run_pipeline_bytes,
    validate_pipeline_config,
)


def _pdf_bytes() -> bytes:
    document = fitz.open()
    for page_number in range(1, 3):
        page = document.new_page()
        page.insert_text((72, 72), f"Control {page_number}", fontsize=18)
        page.insert_textbox(
            fitz.Rect(72, 110, 520, 740),
            (
                f"{page_number}.1 Maintain Secure Inventory\n"
                + "Maintain an accurate inventory of enterprise assets and review it regularly. "
                * 12
            ),
            fontsize=10,
        )
    payload = document.tobytes()
    document.close()
    return payload


def _record(
    chunk_id: str,
    text: str,
    *,
    element_type: str = "narrative",
    clause: str | None = None,
    page_start: int = 1,
    page_end: int = 1,
) -> dict:
    return {
        "text": text,
        "metadata": {
            "source_file": "test.pdf",
            "doc_title": "Test",
            "chunk_id": chunk_id,
            "chunk_index": 0,
            "page_start": page_start,
            "page_end": page_end,
            "breadcrumb": ["Control 1"],
            "clause_number": clause,
            "token_count": 42,
            "element_type": element_type,
            "table_annotation": None,
        },
    }


def test_pipeline_config_round_trip_and_validation() -> None:
    config = PipelineConfig(
        max_tokens=320,
        min_tokens=35,
        overlap_tokens=45,
        heading_size_ratio=1.25,
        boilerplate_page_frequency=0.30,
        ocr_enabled=False,
        table_column_labels=("IG1", "IG4"),
    )

    restored = pipeline_config_from_payload(pipeline_config_payload(config))

    assert restored == config
    assert validate_pipeline_config(restored) == []
    assert validate_pipeline_config(
        PipelineConfig(max_tokens=100, min_tokens=120, overlap_tokens=100)
    ) == [
        "Minimum chunk tokens cannot exceed maximum chunk tokens.",
        "Overlap must be smaller than the maximum chunk size.",
    ]


def test_pdf_inspection_reports_pages_and_corruption() -> None:
    valid = inspect_pdf_bytes(_pdf_bytes())
    invalid = inspect_pdf_bytes(b"not a pdf")

    assert valid["ok"] is True
    assert valid["page_count"] == 2
    assert invalid["ok"] is False
    assert "Unreadable PDF" in invalid["error"]


def test_wrapper_runs_unchanged_pipeline_and_reports_real_stages() -> None:
    original_iter_pages = parser_core.PDFTextExtractor.iter_pages
    original_heading_fit = parser_core.HeadingClassifier.fit
    events: list[dict] = []

    result = run_pipeline_bytes(
        _pdf_bytes(),
        "sample.pdf",
        pipeline_config_payload(PipelineConfig(max_tokens=180, min_tokens=20)),
        events.append,
    )

    assert result["chunks"]
    assert result["file_name"] == "sample.pdf"
    assert result["processing_time"] >= 0
    completed = {
        event["stage"]
        for event in events
        if event["event"] == "stage" and event["state"] == "complete"
    }
    assert completed == {"extraction", "boilerplate", "headings", "tables", "chunking"}
    assert any(event["event"] == "log" for event in events)
    assert [report["state"] for report in result["stage_reports"]] == [
        "complete"
    ] * 5
    assert all(
        report["duration_seconds"] is not None
        for report in result["stage_reports"]
    )
    reports = {
        report["stage"]: report["details"]
        for report in result["stage_reports"]
    }
    assert reports["extraction"]["pages_extracted"] == 2
    assert reports["extraction"]["lines_extracted"] > 0
    assert reports["chunking"]["final_chunks"] == len(result["chunks"])
    assert reports["chunking"]["total_tokens"] == sum(
        chunk["metadata"]["token_count"] for chunk in result["chunks"]
    )
    manifest = build_chunk_output_manifest(result)
    assert manifest["chunks"]["count"] == len(result["chunks"])
    assert manifest["chunks"]["unique_chunk_ids"] == len(result["chunks"])
    assert parser_core.PDFTextExtractor.iter_pages is original_iter_pages
    assert parser_core.HeadingClassifier.fit is original_heading_fit


def test_filter_table_and_exports_keep_canonical_records() -> None:
    chunks = [
        _record("intro-1", "Introduction to controls"),
        _record(
            "control01-safeguard1.1",
            "Maintain inventory of enterprise assets",
            element_type="clause",
            clause="1.1",
            page_start=2,
            page_end=3,
        ),
    ]

    filtered = filter_chunk_records(
        chunks,
        search="inventory",
        element_types=["clause"],
        page_range=(3, 4),
        clauses_only=True,
    )
    rows = chunk_table_rows(filtered)
    exported = [
        json.loads(line)
        for line in chunks_to_jsonl(filtered).decode("utf-8").splitlines()
    ]

    assert filtered == [chunks[1]]
    assert rows[0]["pages"] == "2–3"
    assert rows[0]["breadcrumb"] == "Control 1"
    assert exported == filtered


def test_streamlit_app_starts_without_frontend_exceptions() -> None:
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["main_navigation"] = "Documents"
    app.session_state["document_studio_workflow"] = "Parse & review"
    app.session_state["pdf_workspace_results"] = [
        {
            "file_name": "test.pdf",
            "file_sha256": "a" * 64,
            "processing_time": 0.25,
            "request_time": 0.25,
            "page_count": 3,
            "cache_hit": False,
            "config": pipeline_config_payload(PipelineConfig()),
            "logs": ["INFO | Produced 2 chunks from 3 pages."],
            "chunks": [
                _record("intro-1", "Introduction to controls"),
                _record("control01-safeguard1.1", "Maintain inventory", clause="1.1"),
            ],
        }
    ]
    app.run()

    assert not app.exception
