"""Professional Streamlit workspace around the unchanged PyMuPDF pipeline."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

import fitz
import pandas as pd
import plotly.express as px
import streamlit as st

import parse as parser_core
from parse import PipelineConfig, PDFChunkingPipeline


PipelineEventSink = Callable[[dict[str, Any]], None]
_PIPELINE_LOCK = threading.RLock()
_STAGE_ORDER = ("extraction", "boilerplate", "headings", "tables", "chunking")
_STAGE_LABELS = {
    "extraction": "Text & layout extraction",
    "boilerplate": "Header/footer removal",
    "headings": "Heading hierarchy detection",
    "tables": "Checklist table parsing",
    "chunking": "Semantic token chunking",
}
_DEFAULT_CONFIG = PipelineConfig()
_WIDGET_DEFAULTS = {
    "pdf_cfg_max_tokens": _DEFAULT_CONFIG.max_tokens,
    "pdf_cfg_min_tokens": _DEFAULT_CONFIG.min_tokens,
    "pdf_cfg_overlap_tokens": _DEFAULT_CONFIG.overlap_tokens,
    "pdf_cfg_heading_size_ratio": _DEFAULT_CONFIG.heading_size_ratio,
    "pdf_cfg_boilerplate_frequency": _DEFAULT_CONFIG.boilerplate_page_frequency,
    "pdf_cfg_ocr_enabled": _DEFAULT_CONFIG.ocr_enabled,
    "pdf_cfg_table_labels": list(_DEFAULT_CONFIG.table_column_labels),
}


def _notify(sink: PipelineEventSink | None, event: str, **payload: Any) -> None:
    if sink is not None:
        sink({"event": event, **payload})


class _LogCollector(logging.Handler):
    def __init__(self, lines: list[str], sink: PipelineEventSink | None):
        super().__init__(level=logging.INFO)
        self.lines = lines
        self.sink = sink
        self.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        self.lines.append(line)
        _notify(self.sink, "log", message=line)


# Wrap parser stages temporarily so the UI can show timing and output details.
@contextmanager
def instrument_pipeline_stages(
    sink: PipelineEventSink | None,
) -> Iterator[None]:
    """Wrap real component boundaries and report detailed, read-only stage outputs."""
    originals: list[tuple[type, str, Any]] = []
    chunking_started: float | None = None
    chunking_details: dict[str, Any] = {
        "sections_processed": 0,
        "provisional_pieces": 0,
        "provisional_tokens": 0,
        "provisional_element_types": Counter(),
    }

    def replace(owner: type, name: str, wrapper: Callable[[Any], Any]) -> None:
        original = getattr(owner, name)
        originals.append((owner, name, original))
        setattr(owner, name, wrapper(original))

    def complete(
        stage: str,
        started: float,
        details: dict[str, Any],
    ) -> None:
        _notify(
            sink,
            "stage",
            stage=stage,
            state="complete",
            duration_seconds=round(time.perf_counter() - started, 4),
            details=details,
        )

    def fail(stage: str, started: float, exc: Exception) -> None:
        _notify(
            sink,
            "stage",
            stage=stage,
            state="error",
            duration_seconds=round(time.perf_counter() - started, 4),
            details={"error": str(exc), "exception_type": type(exc).__name__},
        )

    def tracked_call(
        stage: str,
        summarize: Callable[[tuple[Any, ...], Any], dict[str, Any]],
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def build(original: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                started = time.perf_counter()
                _notify(sink, "stage", stage=stage, state="running")
                try:
                    result = original(*args, **kwargs)
                    details = summarize(args, result)
                except Exception as exc:
                    fail(stage, started, exc)
                    raise
                complete(stage, started, details)
                return result

            return wrapped

        return build

    def summarize_boilerplate(
        args: tuple[Any, ...],
        result: Any,
    ) -> dict[str, Any]:
        owner = args[0]
        pages = args[1] if len(args) > 1 else []
        total_pages = len(pages)
        threshold = max(
            owner._config.boilerplate_min_page_count,
            int(total_pages * owner._config.boilerplate_page_frequency),
        )
        patterns = sorted(result)
        return {
            "input_pages": total_pages,
            "input_lines": sum(len(lines) for lines in pages),
            "frequency_threshold": owner._config.boilerplate_page_frequency,
            "minimum_page_count": owner._config.boilerplate_min_page_count,
            "effective_page_threshold": threshold,
            "recurring_patterns_detected": len(patterns),
            "pattern_examples": patterns[:12],
        }

    def summarize_headings(
        args: tuple[Any, ...],
        _result: Any,
    ) -> dict[str, Any]:
        owner = args[0]
        pages = args[1] if len(args) > 1 else []
        headings = [
            line
            for lines in pages
            for line in lines
            if owner.classify(line) is not None
        ]
        return {
            "input_pages": len(pages),
            "input_lines": sum(len(lines) for lines in pages),
            "body_font_size": owner._body_size,
            "heading_font_sizes": list(owner._level_sizes),
            "heading_size_ratio": owner._config.heading_size_ratio,
            "heading_candidates": len(headings),
            "heading_examples": [
                {
                    "text": line.text,
                    "page": line.page_number,
                    "font_size": line.font_size,
                    "level": owner.classify(line),
                }
                for line in headings[:12]
            ],
        }

    def summarize_tables(
        args: tuple[Any, ...],
        result: Any,
    ) -> dict[str, Any]:
        owner = args[0]
        annotations = list(result.values())
        groups = Counter(
            group
            for annotation in annotations
            for group in annotation.applicable_groups
        )
        return {
            "pages_scanned": args[1].page_count if len(args) > 1 else 0,
            "configured_column_labels": list(owner._config.table_column_labels),
            "annotations_detected": len(annotations),
            "annotations_with_groups": sum(
                bool(annotation.applicable_groups) for annotation in annotations
            ),
            "implementation_group_counts": dict(sorted(groups.items())),
            "clause_examples": sorted(result)[:15],
        }

    def tracked_pages(original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            owner = args[0]
            details = {
                "pages_extracted": 0,
                "lines_extracted": 0,
                "characters_extracted": 0,
                "text_blocks": 0,
                "image_blocks": 0,
                "low_text_pages": [],
                "ocr_enabled": owner._config.ocr_enabled,
                "ocr_min_chars": owner._config.ocr_min_chars,
                "ocr_dpi": owner._config.ocr_dpi,
                "ocr_language": owner._config.ocr_lang,
            }
            _notify(sink, "stage", stage="extraction", state="running")
            try:
                for page_number, lines, raw in original(*args, **kwargs):
                    character_count = sum(len(line.text) for line in lines)
                    details["pages_extracted"] += 1
                    details["lines_extracted"] += len(lines)
                    details["characters_extracted"] += character_count
                    details["text_blocks"] += sum(
                        block.get("type") == 0 for block in raw.get("blocks", [])
                    )
                    details["image_blocks"] += sum(
                        block.get("type") == 1 for block in raw.get("blocks", [])
                    )
                    if character_count < owner._config.ocr_min_chars:
                        details["low_text_pages"].append(page_number)
                    yield page_number, lines, raw
            except Exception as exc:
                fail("extraction", started, exc)
                raise
            complete("extraction", started, details)

        return wrapped

    def tracked_chunk_section(original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            nonlocal chunking_started
            if chunking_started is None:
                chunking_started = time.perf_counter()
            _notify(sink, "stage", stage="chunking", state="running")
            try:
                result = original(*args, **kwargs)
            except Exception as exc:
                fail("chunking", chunking_started, exc)
                raise
            owner = args[0]
            chunking_details["sections_processed"] += 1
            chunking_details["provisional_pieces"] += len(result)
            for text, element_type, _clause, _annotation in result:
                chunking_details["provisional_tokens"] += owner._tokens.count(text)
                chunking_details["provisional_element_types"][element_type] += 1
            return result

        return wrapped

    def tracked_chunk_merge(original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            nonlocal chunking_started
            if chunking_started is None:
                chunking_started = time.perf_counter()
            _notify(sink, "stage", stage="chunking", state="running")
            try:
                result = original(*args, **kwargs)
            except Exception as exc:
                fail("chunking", chunking_started, exc)
                raise

            token_counts = [chunk.metadata.token_count for chunk in result]
            element_types = Counter(
                chunk.metadata.element_type for chunk in result
            )
            pages = [
                page
                for chunk in result
                for page in (chunk.metadata.page_start, chunk.metadata.page_end)
            ]
            details = {
                **chunking_details,
                "provisional_element_types": dict(
                    sorted(chunking_details["provisional_element_types"].items())
                ),
                "final_chunks": len(result),
                "total_tokens": sum(token_counts),
                "minimum_tokens": min(token_counts, default=0),
                "average_tokens": (
                    round(sum(token_counts) / len(token_counts), 2)
                    if token_counts
                    else 0
                ),
                "median_tokens": (
                    round(statistics.median(token_counts), 2)
                    if token_counts
                    else 0
                ),
                "maximum_tokens": max(token_counts, default=0),
                "final_element_types": dict(sorted(element_types.items())),
                "clause_chunks": sum(
                    bool(chunk.metadata.clause_number) for chunk in result
                ),
                "table_annotated_chunks": sum(
                    chunk.metadata.table_annotation is not None for chunk in result
                ),
                "unique_breadcrumbs": len(
                    {chunk.metadata.breadcrumb for chunk in result}
                ),
                "page_start": min(pages, default=0),
                "page_end": max(pages, default=0),
                "configured_min_tokens": args[0]._config.min_tokens,
                "configured_max_tokens": args[0]._config.max_tokens,
                "configured_overlap_tokens": args[0]._config.overlap_tokens,
            }
            complete("chunking", chunking_started, details)
            return result

        return wrapped

    replace(parser_core.PDFTextExtractor, "iter_pages", tracked_pages)
    replace(
        parser_core.BoilerplateFilter,
        "fit",
        tracked_call("boilerplate", summarize_boilerplate),
    )
    replace(
        parser_core.HeadingClassifier,
        "fit",
        tracked_call("headings", summarize_headings),
    )
    replace(
        parser_core.ChecklistTableParser,
        "parse_document",
        tracked_call("tables", summarize_tables),
    )
    replace(parser_core.SemanticChunker, "chunk_section", tracked_chunk_section)
    replace(parser_core.PDFChunkingPipeline, "_merge_global_chunks", tracked_chunk_merge)

    try:
        yield
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


# Convert parser settings between dataclasses and JSON-safe dictionaries.

def pipeline_config_payload(config: PipelineConfig) -> dict[str, Any]:
    payload = dataclasses.asdict(config)
    payload["table_column_labels"] = list(config.table_column_labels)
    return payload


def pipeline_config_from_payload(payload: dict[str, Any]) -> PipelineConfig:
    values = dict(payload)
    values["table_column_labels"] = tuple(values["table_column_labels"])
    return PipelineConfig(**values)


def validate_pipeline_config(config: PipelineConfig) -> list[str]:
    errors: list[str] = []
    if config.min_tokens > config.max_tokens:
        errors.append("Minimum chunk tokens cannot exceed maximum chunk tokens.")
    if config.overlap_tokens >= config.max_tokens:
        errors.append("Overlap must be smaller than the maximum chunk size.")
    if not config.table_column_labels:
        errors.append("Add at least one table-column label.")
    return errors


def stage_reports_from_events(
    events: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    reports = {
        stage: {
            "stage": stage,
            "label": _STAGE_LABELS[stage],
            "state": "pending",
            "duration_seconds": None,
            "details": {},
        }
        for stage in _STAGE_ORDER
    }
    for event in events:
        if event.get("event") != "stage" or event.get("stage") not in reports:
            continue
        report = reports[event["stage"]]
        report["state"] = event.get("state", report["state"])
        if "duration_seconds" in event:
            report["duration_seconds"] = event["duration_seconds"]
        if event.get("details"):
            report["details"] = event["details"]
    return [reports[stage] for stage in _STAGE_ORDER]


def _percentile(values: Sequence[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return int(ordered[index])


# Summarize parsed chunks for downloads, reports, and future API responses.

def build_chunk_output_manifest(result: dict[str, Any]) -> dict[str, Any]:
    chunks = result.get("chunks") or []
    metadata = [chunk.get("metadata") or {} for chunk in chunks]
    token_counts = [int(item.get("token_count", 0)) for item in metadata]
    element_types = Counter(
        str(item.get("element_type") or "unknown") for item in metadata
    )
    page_numbers = {
        page
        for item in metadata
        for page in range(
            int(item.get("page_start", 0)),
            int(item.get("page_end", item.get("page_start", 0))) + 1,
        )
        if page > 0
    }
    configured_min = int((result.get("config") or {}).get("min_tokens", 0))
    configured_max = int((result.get("config") or {}).get("max_tokens", 0))
    return {
        "document": {
            "file_name": result.get("file_name"),
            "sha256": result.get("file_sha256"),
            "reported_pages": result.get("page_count"),
            "covered_pages": sorted(page_numbers),
            "processing_seconds": round(float(result.get("processing_time", 0)), 4),
            "request_seconds": round(float(result.get("request_time", 0)), 4),
            "cache_hit": bool(result.get("cache_hit")),
        },
        "chunks": {
            "count": len(chunks),
            "unique_chunk_ids": len(
                {item.get("chunk_id") for item in metadata if item.get("chunk_id")}
            ),
            "total_tokens": sum(token_counts),
            "average_tokens": (
                round(sum(token_counts) / len(token_counts), 2)
                if token_counts
                else 0
            ),
            "minimum_tokens": min(token_counts, default=0),
            "median_tokens": (
                round(statistics.median(token_counts), 2)
                if token_counts
                else 0
            ),
            "p95_tokens": _percentile(token_counts, 0.95),
            "maximum_tokens": max(token_counts, default=0),
            "below_configured_minimum": sum(
                value < configured_min for value in token_counts
            ),
            "above_configured_maximum": sum(
                value > configured_max for value in token_counts
            ),
            "element_types": dict(sorted(element_types.items())),
            "clause_chunks": sum(bool(item.get("clause_number")) for item in metadata),
            "table_annotated_chunks": sum(
                item.get("table_annotation") is not None for item in metadata
            ),
            "unique_breadcrumbs": len(
                {
                    tuple(item.get("breadcrumb") or [])
                    for item in metadata
                }
            ),
            "jsonl_bytes": len(chunks_to_jsonl(chunks)),
        },
        "configuration": result.get("config") or {},
        "stage_outputs": result.get("stage_reports") or [],
    }


# Check an upload before sending it to the more expensive parser.
@st.cache_data(show_spinner=False, max_entries=64)
def inspect_pdf_bytes(file_bytes: bytes) -> dict[str, Any]:
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            if document.needs_pass:
                return {"ok": False, "error": "Password-protected PDF"}
            if document.page_count < 1:
                return {"ok": False, "error": "PDF contains no pages"}
            metadata = document.metadata or {}
            return {
                "ok": True,
                "page_count": document.page_count,
                "title": (metadata.get("title") or "").strip(),
            }
    except Exception as exc:
        return {"ok": False, "error": f"Unreadable PDF: {exc}"}


def _safe_pdf_name(file_name: str) -> str:
    name = Path(file_name).name
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


# This headless function is the main parsing boundary for Streamlit or FastAPI.

def run_pipeline_bytes(
    file_bytes: bytes,
    file_name: str,
    config_payload: dict[str, Any],
    event_sink: PipelineEventSink | None = None,
) -> dict[str, Any]:
    """Run the core pipeline unchanged against a short-lived uploaded PDF."""
    config = pipeline_config_from_payload(config_payload)
    logs: list[str] = []
    stage_events: list[dict[str, Any]] = []

    def capture_event(event: dict[str, Any]) -> None:
        if event.get("event") == "stage":
            stage_events.append(dict(event))
        if event_sink is not None:
            event_sink(event)

    collector = _LogCollector(logs, capture_event)
    parser_logger = parser_core.logger
    previous_level = parser_logger.level
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="rag-pdf-") as temp_dir:
        pdf_path = Path(temp_dir) / _safe_pdf_name(file_name)
        pdf_path.write_bytes(file_bytes)
        with _PIPELINE_LOCK:
            parser_logger.addHandler(collector)
            parser_logger.setLevel(logging.INFO)
            try:
                with instrument_pipeline_stages(capture_event):
                    chunks = PDFChunkingPipeline(config).run(pdf_path)
            finally:
                parser_logger.removeHandler(collector)
                parser_logger.setLevel(previous_level)

    elapsed = time.perf_counter() - started
    return {
        "file_name": file_name,
        "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "processing_time": elapsed,
        "config": config_payload,
        "logs": logs,
        "stage_reports": stage_reports_from_events(stage_events),
        "chunks": [
            {"text": chunk.text, "metadata": chunk.metadata.to_json()}
            for chunk in chunks
        ],
    }


@st.cache_data(show_spinner=False, max_entries=24)
def parse_pdf_cached(
    file_bytes: bytes,
    file_name: str,
    config_payload: dict[str, Any],
    _event_sink: PipelineEventSink | None = None,
) -> dict[str, Any]:
    """Cache by PDF bytes, file name, and complete parser configuration."""
    return run_pipeline_bytes(file_bytes, file_name, config_payload, _event_sink)


def chunks_to_jsonl(chunks: Sequence[dict[str, Any]]) -> bytes:
    lines = [json.dumps(chunk, ensure_ascii=False) for chunk in chunks]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


# Apply the review filters without changing the original chunk list.

def filter_chunk_records(
    chunks: Sequence[dict[str, Any]],
    search: str = "",
    element_types: Sequence[str] | None = None,
    page_range: tuple[int, int] | None = None,
    clauses_only: bool = False,
) -> list[dict[str, Any]]:
    query = search.strip().lower()
    allowed_types = set(element_types or [])
    filtered: list[dict[str, Any]] = []
    for record in chunks:
        metadata = record["metadata"]
        if allowed_types and metadata.get("element_type") not in allowed_types:
            continue
        if clauses_only and not metadata.get("clause_number"):
            continue
        if page_range is not None:
            start, end = page_range
            if metadata.get("page_end", 0) < start or metadata.get("page_start", 0) > end:
                continue
        breadcrumb = " / ".join(metadata.get("breadcrumb") or [])
        haystack = " ".join(
            [
                record.get("text", ""),
                str(metadata.get("chunk_id") or ""),
                str(metadata.get("clause_number") or ""),
                breadcrumb,
            ]
        ).lower()
        if query and query not in haystack:
            continue
        filtered.append(record)
    return filtered


def chunk_table_rows(chunks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in chunks:
        metadata = record["metadata"]
        page_start = int(metadata.get("page_start", 0))
        page_end = int(metadata.get("page_end", page_start))
        annotation = metadata.get("table_annotation") or {}
        groups = annotation.get("applicable_groups") or []
        text = record.get("text", "")
        rows.append(
            {
                "chunk_id": metadata.get("chunk_id"),
                "breadcrumb": " / ".join(metadata.get("breadcrumb") or []) or "—",
                "clause_number": metadata.get("clause_number") or "—",
                "token_count": int(metadata.get("token_count", 0)),
                "character_count": len(text),
                "pages": str(page_start) if page_start == page_end else f"{page_start}–{page_end}",
                "element_type": metadata.get("element_type") or "unknown",
                "implementation_groups": ", ".join(groups) or "—",
                "preview": " ".join(text.split())[:180],
            }
        )
    return rows


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _reset_pipeline_widgets() -> None:
    for key, value in _WIDGET_DEFAULTS.items():
        st.session_state[key] = list(value) if isinstance(value, list) else value


# Streamlit owns these widgets, but the resulting config is plain Python data.

def render_pipeline_config_sidebar() -> tuple[PipelineConfig, list[str]]:
    for key, value in _WIDGET_DEFAULTS.items():
        st.session_state.setdefault(
            key, list(value) if isinstance(value, list) else value
        )

    with st.sidebar:
        st.divider()
        st.markdown("#### PDF pipeline")
        st.caption("Settings apply to the Parse & review workspace.")

        with st.expander("Chunk sizing", expanded=True):
            st.slider(
                "Maximum tokens",
                min_value=100,
                max_value=1600,
                step=25,
                key="pdf_cfg_max_tokens",
                help="Hard target for each semantic chunk.",
            )
            st.slider(
                "Minimum tokens",
                min_value=1,
                max_value=400,
                step=5,
                key="pdf_cfg_min_tokens",
                help="Smaller adjacent pieces are merged when possible.",
            )
            st.slider(
                "Overlap tokens",
                min_value=0,
                max_value=400,
                step=10,
                key="pdf_cfg_overlap_tokens",
                help="Overlap used when oversized text must be windowed.",
            )

        with st.expander("Document structure"):
            st.slider(
                "Heading size ratio",
                min_value=1.0,
                max_value=2.0,
                step=0.05,
                key="pdf_cfg_heading_size_ratio",
                help="Font-size multiplier used to identify headings.",
            )
            st.slider(
                "Boilerplate page frequency",
                min_value=0.05,
                max_value=0.80,
                step=0.05,
                format="%.2f",
                key="pdf_cfg_boilerplate_frequency",
                help="How often a margin line must recur before removal.",
            )

        with st.expander("OCR & tables"):
            st.toggle(
                "Enable OCR fallback",
                key="pdf_cfg_ocr_enabled",
                help="Uses Tesseract on image pages with little extractable text.",
            )
            current_labels = st.session_state["pdf_cfg_table_labels"]
            label_options = sorted(
                set(_DEFAULT_CONFIG.table_column_labels) | set(current_labels)
            )
            st.multiselect(
                "Table-column labels",
                options=label_options,
                key="pdf_cfg_table_labels",
                accept_new_options=True,
                help="Type a label and press Enter to add it.",
            )
            if st.session_state["pdf_cfg_ocr_enabled"] and shutil.which("tesseract") is None:
                st.warning("OCR is enabled, but Tesseract is not available on PATH.")

        st.button(
            "Reset parser settings",
            on_click=_reset_pipeline_widgets,
            width="stretch",
            help="Restore every exposed PipelineConfig field to its code default.",
        )

    config = dataclasses.replace(
        _DEFAULT_CONFIG,
        max_tokens=int(st.session_state["pdf_cfg_max_tokens"]),
        min_tokens=int(st.session_state["pdf_cfg_min_tokens"]),
        overlap_tokens=int(st.session_state["pdf_cfg_overlap_tokens"]),
        heading_size_ratio=float(st.session_state["pdf_cfg_heading_size_ratio"]),
        boilerplate_page_frequency=float(
            st.session_state["pdf_cfg_boilerplate_frequency"]
        ),
        ocr_enabled=bool(st.session_state["pdf_cfg_ocr_enabled"]),
        table_column_labels=tuple(st.session_state["pdf_cfg_table_labels"]),
    )
    return config, validate_pipeline_config(config)


def _render_empty_state() -> None:
    st.markdown(
        """
        <div class="pdf-empty">
          <div class="pdf-empty-icon">PDF</div>
          <h3>Turn documents into inspectable chunks</h3>
          <p>Upload one or more PDFs, tune the structure-aware parser in the sidebar,
          then review token sizing and metadata before downloading anything.</p>
          <div class="pdf-steps">
            <span><b>1</b> Upload</span>
            <span><b>2</b> Parse & chunk</span>
            <span><b>3</b> Review & export</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _stage_detail_summary(stage: str, details: dict[str, Any]) -> str:
    if not details:
        return ""
    if stage == "extraction":
        return (
            f"{details.get('pages_extracted', 0)} pages · "
            f"{details.get('lines_extracted', 0):,} lines · "
            f"{details.get('characters_extracted', 0):,} characters"
        )
    if stage == "boilerplate":
        return (
            f"{details.get('recurring_patterns_detected', 0)} recurring patterns · "
            f"threshold {details.get('effective_page_threshold', 0)} pages"
        )
    if stage == "headings":
        return (
            f"{details.get('heading_candidates', 0)} heading candidates · "
            f"body font {details.get('body_font_size', 0):g}pt"
        )
    if stage == "tables":
        return (
            f"{details.get('annotations_detected', 0)} annotations · "
            f"{details.get('annotations_with_groups', 0)} with implementation groups"
        )
    if stage == "chunking":
        return (
            f"{details.get('final_chunks', 0)} chunks · "
            f"{details.get('total_tokens', 0):,} tokens · "
            f"{details.get('minimum_tokens', 0)}–{details.get('maximum_tokens', 0)} tokens/chunk"
        )
    return ""


def _stage_markdown(
    states: dict[str, str],
    reports: dict[str, dict[str, Any]] | None = None,
) -> str:
    symbols = {"pending": "○", "running": "◉", "complete": "✓", "error": "!"}
    lines = []
    reports = reports or {}
    for stage in _STAGE_ORDER:
        line = f"{symbols[states[stage]]} **{_STAGE_LABELS[stage]}**"
        event = reports.get(stage) or {}
        summary = _stage_detail_summary(stage, event.get("details") or {})
        duration = event.get("duration_seconds")
        if summary:
            line += f"  \n&nbsp;&nbsp;&nbsp;&nbsp;{summary}"
            if duration is not None:
                line += f" · {duration:.2f}s"
        lines.append(line)
    return "  \n".join(lines)


def _run_uploaded_files(
    uploads: Sequence[Any],
    inspections: dict[str, dict[str, Any]],
    config: PipelineConfig,
) -> list[dict[str, Any]]:
    valid = [
        upload
        for upload in uploads
        if inspections[hashlib.sha256(upload.getvalue()).hexdigest()]["ok"]
    ]
    results: list[dict[str, Any]] = []
    overall = st.progress(0.0, text=f"Preparing {len(valid)} PDF(s)…")

    for file_index, upload in enumerate(valid, start=1):
        file_bytes = upload.getvalue()
        digest = hashlib.sha256(file_bytes).hexdigest()
        info = inspections[digest]
        states = {stage: "pending" for stage in _STAGE_ORDER}
        stage_events: list[dict[str, Any]] = []
        stage_details: dict[str, dict[str, Any]] = {}
        live_logs: list[str] = []

        with st.status(
            f"{file_index}/{len(valid)} · {upload.name}",
            expanded=True,
        ) as status:
            file_progress = st.progress(0.0, text="Starting extraction…")
            stage_slot = st.empty()
            log_slot = st.empty()
            stage_slot.markdown(_stage_markdown(states))

            def event_sink(event: dict[str, Any]) -> None:
                stage_events.append(event)
                if event["event"] == "stage":
                    stage = event["stage"]
                    states[stage] = event["state"]
                    if event.get("details"):
                        stage_details[stage] = event
                    stage_index = _STAGE_ORDER.index(stage)
                    fraction = (
                        (stage_index + (1.0 if event["state"] == "complete" else 0.15))
                        / len(_STAGE_ORDER)
                    )
                    file_progress.progress(
                        min(fraction, 1.0),
                        text=f"{_STAGE_LABELS[stage]} · {fraction:.0%}",
                    )
                    stage_slot.markdown(
                        _stage_markdown(states, stage_details)
                    )
                elif event["event"] == "log":
                    live_logs.append(event["message"])
                    log_slot.code("\n".join(live_logs[-8:]), language="text")

            try:
                started = time.perf_counter()
                result = parse_pdf_cached(
                    file_bytes,
                    upload.name,
                    pipeline_config_payload(config),
                    _event_sink=event_sink,
                )
                wall_time = time.perf_counter() - started
                result["page_count"] = info["page_count"]
                result["cache_hit"] = not any(
                    event["event"] == "stage" for event in stage_events
                )
                result["request_time"] = wall_time
                for report in result.get("stage_reports", []):
                    stage_details[report["stage"]] = report
                for stage in _STAGE_ORDER:
                    states[stage] = "complete"
                stage_slot.markdown(_stage_markdown(states, stage_details))
                file_progress.progress(1.0, text="Pipeline complete")
                label = (
                    f"{upload.name} · loaded from cache"
                    if result["cache_hit"]
                    else f"{upload.name} · {len(result['chunks'])} chunks"
                )
                status.update(label=label, state="complete", expanded=False)
                results.append(result)
            except Exception as exc:
                for stage, state in states.items():
                    if state == "running":
                        states[stage] = "error"
                stage_slot.markdown(_stage_markdown(states))
                status.update(
                    label=f"{upload.name} · failed",
                    state="error",
                    expanded=True,
                )
                st.error(f"Could not parse {upload.name}: {exc}")
                results.append(
                    {
                        "file_name": upload.name,
                        "file_sha256": digest,
                        "error": str(exc),
                        "page_count": info.get("page_count", 0),
                    }
                )

        overall.progress(
            file_index / len(valid),
            text=f"Completed {file_index} of {len(valid)} PDF(s)",
        )

    return results


def _render_histogram(result: dict[str, Any]) -> None:
    chunks = result["chunks"]
    values = [chunk["metadata"]["token_count"] for chunk in chunks]
    frame = pd.DataFrame({"Tokens per chunk": values})
    config = result["config"]
    figure = px.histogram(
        frame,
        x="Tokens per chunk",
        nbins=min(36, max(8, int(len(values) ** 0.5) * 2)),
        color_discrete_sequence=["#8B5CF6"],
    )
    figure.add_vline(
        x=config["min_tokens"],
        line_dash="dot",
        line_color="#F59E0B",
        annotation_text="min",
    )
    figure.add_vline(
        x=config["max_tokens"],
        line_dash="dash",
        line_color="#6366F1",
        annotation_text="max",
    )
    figure.update_layout(
        height=300,
        margin=dict(l=8, r=8, t=22, b=8),
        bargap=0.08,
        showlegend=False,
        xaxis_title="Token count",
        yaxis_title="Chunks",
    )
    st.plotly_chart(
        figure,
        width="stretch",
        theme="streamlit",
        config={"displayModeBar": False},
    )


def _render_stage_outputs(
    result: dict[str, Any],
    tab_key: str,
) -> None:
    reports = result.get("stage_reports") or []
    manifest = build_chunk_output_manifest(result)
    st.markdown("#### Stage outputs & processing manifest")
    st.caption(
        "Every stage reports what it received, what it produced, its strategy "
        "configuration, measurable counts, and execution time."
    )

    if reports:
        rows = [
            {
                "Stage": report["label"],
                "Status": report["state"].title(),
                "Duration (s)": report.get("duration_seconds"),
                "Output": _stage_detail_summary(
                    report["stage"], report.get("details") or {}
                ),
            }
            for report in reports
        ]
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Stage": st.column_config.TextColumn(width="medium"),
                "Status": st.column_config.TextColumn(width="small"),
                "Duration (s)": st.column_config.NumberColumn(
                    format="%.3f",
                    width="small",
                ),
                "Output": st.column_config.TextColumn(width="large"),
            },
        )
        selected_stage = st.selectbox(
            "Inspect a stage in detail",
            [report["stage"] for report in reports],
            format_func=lambda stage: _STAGE_LABELS.get(stage, stage.title()),
            key=f"stage_output_{tab_key}",
        )
        selected_report = next(
            report for report in reports if report["stage"] == selected_stage
        )
        with st.expander(
            f"{selected_report['label']} · complete output",
            expanded=True,
        ):
            detail_cols = st.columns([1.6, 1.0])
            with detail_cols[0]:
                st.markdown("##### Measured output")
                st.json(selected_report.get("details") or {}, expanded=True)
            with detail_cols[1]:
                st.markdown("##### Stage execution")
                st.json(
                    {
                        "status": selected_report.get("state"),
                        "duration_seconds": selected_report.get(
                            "duration_seconds"
                        ),
                        "strategy": selected_report.get("stage"),
                    },
                    expanded=True,
                )
    else:
        st.info(
            "This cached result predates detailed stage reporting. Re-run Parse & "
            "Chunk once to populate every stage output."
        )

    with st.expander("Complete document processing manifest"):
        st.json(manifest, expanded=True)
        st.download_button(
            "Download processing manifest · JSON",
            data=json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            file_name=f"{Path(result['file_name']).stem}.processing-manifest.json",
            mime="application/json",
            width="stretch",
            key=f"download_manifest_{tab_key}",
        )


def _render_file_result(result: dict[str, Any], tab_key: str) -> None:
    if result.get("error"):
        st.error(f"Parsing failed: {result['error']}")
        return

    chunks = result["chunks"]
    if not chunks:
        st.warning(
            "The parser completed but produced no chunks. The PDF may be scanned, "
            "empty, encrypted, or require OCR tooling."
        )
        return

    token_counts = [int(chunk["metadata"]["token_count"]) for chunk in chunks]
    page_starts = [int(chunk["metadata"]["page_start"]) for chunk in chunks]
    page_ends = [int(chunk["metadata"]["page_end"]) for chunk in chunks]
    manifest = build_chunk_output_manifest(result)
    chunk_summary = manifest["chunks"]

    primary_metrics = st.columns(4)
    primary_metrics[0].metric("Total chunks", f"{len(chunks):,}")
    primary_metrics[1].metric("Total tokens", f"{chunk_summary['total_tokens']:,}")
    primary_metrics[2].metric(
        "Average / median",
        f"{chunk_summary['average_tokens']:.1f} / {chunk_summary['median_tokens']:.1f}",
    )
    primary_metrics[3].metric(
        "Min / P95 / max",
        (
            f"{chunk_summary['minimum_tokens']} / "
            f"{chunk_summary['p95_tokens']} / "
            f"{chunk_summary['maximum_tokens']}"
        ),
    )

    secondary_metrics = st.columns(4)
    secondary_metrics[0].metric(
        "Page coverage",
        f"{min(page_starts)}–{max(page_ends)}",
    )
    secondary_metrics[1].metric(
        "Clause chunks",
        f"{chunk_summary['clause_chunks']:,}",
    )
    secondary_metrics[2].metric(
        "Table annotated",
        f"{chunk_summary['table_annotated_chunks']:,}",
    )
    secondary_metrics[3].metric(
        "Processing time",
        f"{result['processing_time']:.2f}s",
    )

    _render_stage_outputs(result, tab_key)

    chart_col, export_col = st.columns([1.55, 1.0], gap="large")
    with chart_col:
        with st.container(border=True):
            st.markdown("##### Token distribution")
            st.caption("Dotted lines show the configured minimum and maximum.")
            _render_histogram(result)
    with export_col:
        with st.container(border=True):
            st.markdown("##### Export this document")
            st.caption(
                "Canonical JSONL preserves each chunk's text and complete metadata."
            )
            stem = Path(result["file_name"]).stem
            st.download_button(
                "Download all chunks · JSONL",
                data=chunks_to_jsonl(chunks),
                file_name=f"{stem}.chunks.jsonl",
                mime="application/x-ndjson",
                type="primary",
                width="stretch",
                key=f"download_all_{tab_key}",
            )
            source = "Cached result" if result.get("cache_hit") else "Fresh pipeline run"
            st.caption(
                f"{source} · SHA-256 {result['file_sha256'][:12]}… · "
                f"{result.get('page_count', max(page_ends))} pages"
            )

    st.markdown("#### Chunk browser")
    filter_box = st.container(border=True)
    with filter_box:
        search_col, type_col, clause_col = st.columns([1.6, 1.2, 0.7])
        search = search_col.text_input(
            "Search chunks",
            placeholder="Text, chunk ID, breadcrumb, or clause…",
            key=f"chunk_search_{tab_key}",
        )
        all_types = sorted(
            {chunk["metadata"].get("element_type", "unknown") for chunk in chunks}
        )
        selected_types = type_col.multiselect(
            "Element type",
            all_types,
            default=all_types,
            key=f"chunk_types_{tab_key}",
        )
        clauses_only = clause_col.toggle(
            "Clauses only",
            value=False,
            key=f"chunk_clauses_{tab_key}",
        )
        min_page, max_page = min(page_starts), max(page_ends)
        if min_page < max_page:
            pages = st.slider(
                "Page coverage",
                min_value=min_page,
                max_value=max_page,
                value=(min_page, max_page),
                key=f"chunk_pages_{tab_key}",
            )
        else:
            pages = (min_page, max_page)

    filtered = filter_chunk_records(
        chunks,
        search=search,
        element_types=selected_types,
        page_range=pages,
        clauses_only=clauses_only,
    )
    st.caption(f"Showing {len(filtered):,} of {len(chunks):,} chunks")
    if not filtered:
        st.info("No chunks match the current filters.")
        return

    table = pd.DataFrame(chunk_table_rows(filtered))
    event = st.dataframe(
        table,
        width="stretch",
        height=min(560, 76 + len(table) * 35),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "chunk_id": st.column_config.TextColumn("Chunk ID", width="medium"),
            "breadcrumb": st.column_config.TextColumn("Breadcrumb", width="large"),
            "clause_number": st.column_config.TextColumn("Clause", width="small"),
            "token_count": st.column_config.ProgressColumn(
                "Tokens",
                min_value=0,
                max_value=max(
                    int(result["config"]["max_tokens"]), max(token_counts)
                ),
                format="%d",
                width="small",
            ),
            "character_count": st.column_config.NumberColumn(
                "Characters",
                format="%d",
                width="small",
            ),
            "pages": st.column_config.TextColumn("Pages", width="small"),
            "element_type": st.column_config.TextColumn("Type", width="medium"),
            "implementation_groups": st.column_config.TextColumn(
                "IGs",
                width="small",
            ),
            "preview": st.column_config.TextColumn("Text preview", width="large"),
        },
        key=f"chunk_table_{tab_key}",
    )

    selected_rows = list(event.selection.rows)
    if not selected_rows:
        st.caption("Select one row to inspect its full text and metadata.")
        return

    selected = filtered[int(selected_rows[0])]
    metadata = selected["metadata"]
    with st.expander(
        f"Selected · {metadata['chunk_id']}",
        expanded=True,
    ):
        st.markdown("##### Chunk text")
        st.text_area(
            "Full text",
            selected["text"],
            height=260,
            disabled=True,
            label_visibility="collapsed",
            key=f"selected_text_{tab_key}_{metadata['chunk_id']}",
        )
        metadata_col, download_col = st.columns([1.6, 0.7])
        with metadata_col:
            st.markdown("##### Metadata")
            st.json(metadata, expanded=False)
        with download_col:
            st.markdown("##### Export")
            st.download_button(
                "Download selected · JSON",
                data=json.dumps(selected, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"{metadata['chunk_id']}.json",
                mime="application/json",
                width="stretch",
                key=f"download_selected_{tab_key}_{metadata['chunk_id']}",
            )

    if result.get("logs"):
        with st.expander("Pipeline logger output"):
            st.code("\n".join(result["logs"]), language="text")


def render_results(results: Sequence[dict[str, Any]]) -> None:
    if not results:
        return
    st.markdown("---")
    st.markdown("### Results")
    labels = [
        f"{result['file_name']} · {result.get('page_count', 0)}p"
        for result in results
    ]
    tabs = st.tabs(labels)
    for index, (tab, result) in enumerate(zip(tabs, results)):
        with tab:
            _render_file_result(
                result,
                f"{index}_{result['file_sha256'][:10]}",
            )


def _render_workspace_styles() -> None:
    st.markdown(
        """
        <style>
        .pdf-workbench {
            border: 1px solid var(--border-color);
            border-radius: 1rem;
            padding: 1.25rem 1.35rem;
            background: var(--secondary-background-color);
            margin-bottom: 1rem;
        }
        .pdf-workbench .eyebrow {
            color: var(--primary-color);
            font-size: .72rem;
            font-weight: 750;
            letter-spacing: .12em;
            text-transform: uppercase;
        }
        .pdf-workbench h2 { margin: .3rem 0 .25rem; }
        .pdf-workbench p { opacity: .72; margin: 0; max-width: 760px; }
        .pdf-empty {
            text-align: center;
            border: 1px dashed var(--border-color);
            border-radius: 1rem;
            padding: 3rem 1.5rem;
            background: var(--secondary-background-color);
        }
        .pdf-empty-icon {
            display: inline-grid;
            place-items: center;
            width: 3rem;
            height: 3rem;
            border-radius: .8rem;
            color: white;
            background: linear-gradient(135deg, #6366F1, #8B5CF6);
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .05em;
            box-shadow: 0 .6rem 1.6rem rgba(99, 102, 241, .24);
        }
        .pdf-empty h3 { margin: 1rem 0 .35rem; }
        .pdf-empty p { max-width: 640px; margin: 0 auto; opacity: .7; }
        .pdf-steps {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: .65rem;
            margin-top: 1.25rem;
        }
        .pdf-steps span {
            border: 1px solid var(--border-color);
            border-radius: 999px;
            padding: .4rem .7rem;
            font-size: .82rem;
        }
        .pdf-steps b { color: #6366F1; margin-right: .25rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _write_background_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


# Save uploads and start a worker so parsing survives page reruns.

def _launch_background_parse(
    uploads: Sequence[Any],
    inspections: dict[str, dict[str, Any]],
    config: PipelineConfig,
    signature: str,
) -> dict[str, str]:
    root = Path(__file__).resolve().parent
    runs_dir = root / ".rag_runs"
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    input_dir = runs_dir / "parse-inputs" / token
    request_path = runs_dir / "parse-requests" / f"{token}.json"
    result_path = runs_dir / "parse-results" / f"{token}.json"
    meta_path = runs_dir / f"{token}-parse.json"
    log_path = runs_dir / f"{token}-parse.log"

    files: list[dict[str, Any]] = []
    for index, upload in enumerate(uploads, start=1):
        content = upload.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        if not inspections[digest]["ok"]:
            continue
        safe_name = _safe_pdf_name(upload.name)
        stored_path = input_dir / f"{index:03d}-{safe_name}"
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_bytes(content)
        files.append(
            {
                "path": str(stored_path),
                "name": upload.name,
                "sha256": digest,
                "page_count": inspections[digest].get("page_count", 0),
            }
        )

    _write_background_json(
        request_path,
        {
            "files": files,
            "configuration": pipeline_config_payload(config),
        },
    )
    command = [
        sys.executable,
        str(root / "background_tasks.py"),
        "parse",
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    _write_background_json(
        meta_path,
        {
            "id": token,
            "kind": "parse",
            "label": f"Parse review | {len(files)} PDF(s)",
            "status": "queued",
            "created_at": time.time(),
            "cwd": str(root),
            "log_path": str(log_path),
            "command": command,
            "priority": "background",
        },
    )
    subprocess.Popen(
        [
            sys.executable,
            str(root / "job_runner.py"),
            "--meta",
            str(meta_path),
            "--log",
            str(log_path),
            "--",
            *command,
        ],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "meta_path": str(meta_path),
        "result_path": str(result_path),
        "signature": signature,
    }


@st.fragment(run_every=2)
def _render_background_parse_status(job_info: dict[str, str]) -> None:
    meta_path = Path(job_info["meta_path"])
    if not meta_path.exists():
        st.warning("Preparing the PDF parsing worker...")
        return
    try:
        job = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        st.warning("Waiting for parsing status...")
        return

    status = job.get("status", "queued")
    log_path = Path(job.get("log_path", ""))
    log = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.exists()
        else ""
    )
    matches = re.findall(r"\[parse\s+(\d+)/(\d+)\]", log)
    if matches:
        current, total = (int(value) for value in matches[-1])
        fraction = min((current - 1 + 0.15) / max(total, 1), 0.95)
        label = f"Background PDF parsing | document {current}/{total}"
    else:
        fraction = 0.0
        label = "Background PDF parsing queued"

    if status == "completed":
        result_path = Path(job_info["result_path"])
        if not result_path.exists():
            st.warning("Parsing finished; waiting for its result artifact...")
            return
        st.session_state["pdf_workspace_results"] = json.loads(
            result_path.read_text(encoding="utf-8")
        )
        st.session_state["pdf_workspace_signature"] = job_info["signature"]
        st.session_state.pop("pdf_workspace_active_job", None)
        st.rerun()
    elif status == "failed":
        st.error("The background PDF parsing worker failed.")
        st.code(log[-12000:], language="text")
        if st.button("Dismiss failed parsing job", key="dismiss_failed_parse"):
            st.session_state.pop("pdf_workspace_active_job", None)
            st.rerun()
    else:
        st.progress(fraction, text=label)
        st.caption(
            "Parsing is running at reduced CPU priority. The Assistant remains "
            "available for interactive questions."
        )
        if log:
            with st.expander("Live parser log"):
                st.code(log[-12000:], language="text")


# This function contains only the Streamlit parsing-review interface.

def render_pdf_parsing_workspace() -> None:
    _render_workspace_styles()
    config, config_errors = render_pipeline_config_sidebar()
    active_parse = st.session_state.get("pdf_workspace_active_job")
    if active_parse is not None:
        _render_background_parse_status(active_parse)

    st.markdown(
        """
        <div class="pdf-workbench">
          <div class="eyebrow">PDF parsing workbench</div>
          <h2>Upload, tune, inspect</h2>
          <p>Run the existing layout-aware PyMuPDF pipeline without indexing.
          Work continues as a durable background job while you use the Assistant.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    uploads = st.file_uploader(
        "Upload PDF documents",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload one or more PDFs. They are processed sequentially.",
        key="pdf_workspace_uploads",
    )
    if not uploads:
        _render_empty_state()
        stored = st.session_state.get("pdf_workspace_results")
        if stored:
            st.caption("Previous in-session results are still available below.")
            render_results(stored)
        return

    inspections: dict[str, dict[str, Any]] = {}
    inventory: list[dict[str, Any]] = []
    for upload in uploads:
        file_bytes = upload.getvalue()
        digest = hashlib.sha256(file_bytes).hexdigest()
        info = inspect_pdf_bytes(file_bytes)
        inspections[digest] = info
        inventory.append(
            {
                "File": upload.name,
                "Size": _format_size(len(file_bytes)),
                "Pages": info.get("page_count", "—"),
                "Status": "Ready" if info["ok"] else info["error"],
            }
        )

    st.dataframe(
        pd.DataFrame(inventory),
        width="stretch",
        hide_index=True,
        column_config={
            "File": st.column_config.TextColumn("File", width="large"),
            "Size": st.column_config.TextColumn("Size", width="small"),
            "Pages": st.column_config.NumberColumn("Pages", width="small"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
        },
    )

    for row in inventory:
        if row["Status"] != "Ready":
            st.error(f"{row['File']}: {row['Status']}")

    for error in config_errors:
        st.error(error)

    valid_count = sum(
        1
        for upload in uploads
        if inspections[hashlib.sha256(upload.getvalue()).hexdigest()]["ok"]
    )
    run_clicked = st.button(
        f"Parse & Chunk {valid_count} PDF{'s' if valid_count != 1 else ''}",
        type="primary",
        width="stretch",
        disabled=not valid_count or bool(config_errors) or active_parse is not None,
    )

    signature_payload = {
        "files": [
            {
                "name": upload.name,
                "sha256": hashlib.sha256(upload.getvalue()).hexdigest(),
            }
            for upload in uploads
        ],
        "config": pipeline_config_payload(config),
    }
    current_signature = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    if run_clicked:
        active_parse = _launch_background_parse(
            uploads,
            inspections,
            config,
            current_signature,
        )
        st.session_state["pdf_workspace_active_job"] = active_parse
        st.success("PDF parsing started in the background.")
        st.rerun()

    stored_results = st.session_state.get("pdf_workspace_results", [])
    stored_signature = st.session_state.get("pdf_workspace_signature")
    if stored_results and stored_signature != current_signature:
        st.info(
            "The results below use a previous upload/configuration. "
            "Choose Parse & Chunk to refresh them."
        )
    render_results(stored_results)
