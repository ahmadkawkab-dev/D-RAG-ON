"""Selective MinerU2.5 visual supplements for the deterministic PDF corpus.

PyMuPDF remains the authoritative parser. MinerU is invoked only for pages
selected as visually difficult (or explicitly requested), and its recognized
content becomes additional, provenance-marked chunks rather than replacing the
existing corpus.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Sequence

import fitz
from PIL import Image

from parse import Chunk, ChunkMetadata, PipelineConfig, SemanticChunker, TokenCounter


logger = logging.getLogger("mineru_parser")

DEFAULT_MINERU_MODEL = "opendatalab/MinerU2.5-2509-1.2B"
_CACHE_SCHEMA_VERSION = 1
_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.IGNORECASE)


@dataclass(frozen=True)
class MinerUConfig:
    """Independent settings so the frozen PyMuPDF parser config stays intact."""

    mode: Literal["off", "selective", "all"] = "off"
    model_name: str = DEFAULT_MINERU_MODEL
    device: str | None = None
    dpi: int = 200
    max_pages: int = 12
    pages: tuple[int, ...] = ()
    cache_dir: Path = Path(".mineru_cache")
    min_text_chars: int = 160
    min_source_overlap: float = 0.35

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


@dataclass(frozen=True)
class PageSelection:
    page_number: int
    reasons: tuple[str, ...]
    pymupdf_text: str


# Turn values like 4,9-12 into validated one-based page numbers.

def parse_page_spec(value: str) -> tuple[int, ...]:
    """Parse one-based page specifications such as ``2,5-7,12``."""
    pages: set[int] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = (part.strip() for part in item.split("-", 1))
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"Invalid MinerU page range: {item!r}")
            start, end = int(start_text), int(end_text)
            if start < 1 or end < start:
                raise ValueError(f"Invalid MinerU page range: {item!r}")
            pages.update(range(start, end + 1))
        elif item.isdigit() and int(item) >= 1:
            pages.add(int(item))
        else:
            raise ValueError(f"Invalid MinerU page number: {item!r}")
    return tuple(sorted(pages))


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def html_table_to_markdown(value: str) -> str:
    parser = _TableHTMLParser()
    parser.feed(value)
    if not parser.rows:
        return re.sub(r"<[^>]+>", " ", value).strip()
    width = max(len(row) for row in parser.rows)
    rows = [row + [""] * (width - len(row)) for row in parser.rows]
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    if len(lines) > 1:
        lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def _normalize_text(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.lower()))


def _block_value(block: Any, name: str, default=None):
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


# MinerU adds optional visual chunks without replacing the main PyMuPDF output.

class MinerU2_5Assistant:
    """Lazy, cache-aware MinerU runner with an explicit unload lifecycle."""

    def __init__(self, config: MinerUConfig):
        self.config = config
        self._model = None
        self._processor = None
        self._client = None
        self._torch = None

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def select_pages(self, document: fitz.Document) -> list[PageSelection]:
        if not self.config.enabled:
            return []

        forced = set(self.config.pages)
        selections: list[PageSelection] = []
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            text = page.get_text("text", sort=True).strip()
            compact = " ".join(text.split())
            upper = compact.upper()
            reasons: list[str] = []

            if self.config.mode == "all":
                reasons.append("all_pages")
            if page_number in forced:
                reasons.append("explicit_page")
            if self.config.mode == "selective":
                if len(compact) < self.config.min_text_chars:
                    reasons.append("low_text")
                if page.get_images(full=True) and len(compact) < self.config.min_text_chars * 5:
                    reasons.append("image_heavy")
                if (
                    "SAFEGUARDS TOTAL" in upper
                    and "IG1" in upper
                    and "IG2" in upper
                    and "IG3" in upper
                ):
                    reasons.append("cis_summary_table")

            if reasons:
                selections.append(PageSelection(page_number, tuple(dict.fromkeys(reasons)), text))

        existing_pages = {item.page_number for item in selections}
        missing_forced = sorted(forced - existing_pages)
        if missing_forced:
            logger.warning("Requested MinerU pages do not exist: %s", missing_forced)

        priority = {
            "explicit_page": 0,
            "cis_summary_table": 1,
            "low_text": 2,
            "image_heavy": 3,
            "all_pages": 4,
        }
        selections.sort(key=lambda item: (min(priority[r] for r in item.reasons), item.page_number))
        if self.config.max_pages > 0 and len(selections) > self.config.max_pages:
            logger.warning(
                "MinerU selected %d pages; limiting this run to %d.",
                len(selections), self.config.max_pages,
            )
            selections = selections[: self.config.max_pages]
        return selections

    def supplement_chunks(
        self,
        pdf_path: Path,
        base_chunks: Sequence[Chunk],
        pipeline_config: PipelineConfig,
    ) -> list[Chunk]:
        if not self.config.enabled:
            return []

        pdf_path = Path(pdf_path)
        pdf_digest = self._sha256(pdf_path)
        supplements: list[Chunk] = []
        with fitz.open(pdf_path) as document:
            selections = self.select_pages(document)
            if not selections:
                logger.info("MinerU found no pages requiring visual assistance in %s.", pdf_path.name)
                return []

            logger.info(
                "MinerU will inspect %d/%d page(s) in %s: %s",
                len(selections), len(document), pdf_path.name,
                ", ".join(str(item.page_number) for item in selections),
            )
            doc_title = (document.metadata or {}).get("title") or pdf_path.stem
            token_counter = TokenCounter(pipeline_config.encoding_name)
            chunker = SemanticChunker(pipeline_config, token_counter)

            supplement_index = 0
            for current, selection in enumerate(selections, start=1):
                logger.info(
                    "[mineru %d/%d] page %d (%s)",
                    current, len(selections), selection.page_number, ", ".join(selection.reasons),
                )
                blocks = self._extract_page(
                    document[selection.page_number - 1], pdf_digest, selection.page_number
                )
                text = self.blocks_to_text(blocks)
                base_text = "\n".join(
                    chunk.text
                    for chunk in base_chunks
                    if chunk.metadata.page_start <= selection.page_number <= chunk.metadata.page_end
                )
                valid, reason = self._validate_supplement(text, base_text, selection.reasons)
                if not valid:
                    logger.warning(
                        "MinerU page %d supplement rejected: %s", selection.page_number, reason
                    )
                    continue
                if self._is_redundant(text, base_text):
                    logger.info(
                        "MinerU page %d added no novel structure; skipping.", selection.page_number
                    )
                    continue

                breadcrumb = ("MinerU2.5 visual supplement", f"Page {selection.page_number}")
                pieces = chunker.chunk_section(
                    text, breadcrumb, selection.page_number, selection.page_number, {}
                )
                for part_number, (piece, _etype, clause, _annotation) in enumerate(
                    pieces, start=1
                ):
                    chunk_id = (
                        f"{pdf_path.stem}-mineru-page{selection.page_number:04d}"
                        f"-part{part_number:02d}"
                    )
                    metadata = ChunkMetadata(
                        source_file=pdf_path.name,
                        doc_title=doc_title,
                        chunk_id=chunk_id,
                        chunk_index=len(base_chunks) + supplement_index,
                        page_start=selection.page_number,
                        page_end=selection.page_number,
                        breadcrumb=breadcrumb,
                        clause_number=clause,
                        token_count=token_counter.count(piece),
                        element_type="mineru_visual_supplement",
                        table_annotation=None,
                    )
                    supplements.append(Chunk(text=piece, metadata=metadata))
                    supplement_index += 1

        logger.info(
            "MinerU produced %d supplemental chunk(s) for %s.", len(supplements), pdf_path.name
        )
        return supplements

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            import torch
            from mineru_vl_utils import MinerUClient
            from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
        except ImportError as exc:
            raise RuntimeError(
                "MinerU support is not installed. Run `uv sync --extra mineru` first."
            ) from exc

        if self.config.device in {None, "auto"}:
            device_map: str | dict[str, str] = "auto"
        else:
            device_map = {"": self.config.device}

        logger.info("Loading MinerU2.5 '%s' on %s.", self.config.model_name, device_map)
        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.config.model_name,
            dtype="auto",
            device_map=device_map,
            low_cpu_mem_usage=True,
        ).eval()
        self._processor = AutoProcessor.from_pretrained(
            self.config.model_name, use_fast=True
        )
        self._client = MinerUClient(
            backend="transformers", model=self._model, processor=self._processor
        )
        self._torch = torch

    def _extract_page(
        self, page: fitz.Page, pdf_digest: str, page_number: int
    ) -> list[dict[str, Any]]:
        cache_path = self._cache_path(pdf_digest, page_number)
        cached = self._read_cache(cache_path)
        if cached is not None:
            logger.info("Using cached MinerU result for page %d.", page_number)
            return cached

        self._ensure_client()
        pixmap = page.get_pixmap(dpi=self.config.dpi, alpha=False, colorspace=fitz.csRGB)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        try:
            raw_blocks = self._client.two_step_extract(image)
        finally:
            image.close()

        blocks = [self._serialize_block(block) for block in raw_blocks]
        self._write_cache(cache_path, pdf_digest, page_number, blocks)
        return blocks

    @staticmethod
    def _serialize_block(block: Any) -> dict[str, Any]:
        bbox = _block_value(block, "bbox", []) or []
        return {
            "type": str(_block_value(block, "type", "text")),
            "bbox": [float(value) for value in bbox],
            "angle": _block_value(block, "angle"),
            "content": _block_value(block, "content"),
        }

    @staticmethod
    def blocks_to_text(blocks: Sequence[dict[str, Any]]) -> str:
        ordered = sorted(
            blocks,
            key=lambda block: (
                (block.get("bbox") or [0, 0, 0, 0])[1],
                (block.get("bbox") or [0, 0, 0, 0])[0],
            ),
        )
        parts: list[str] = []
        for block in ordered:
            content = str(block.get("content") or "").strip()
            if not content:
                continue
            block_type = str(block.get("type") or "text").lower()
            if "table" in block_type or "<table" in content.lower():
                content = html_table_to_markdown(content)
            elif "equation" in block_type or "formula" in block_type:
                content = f"$$\n{content}\n$$"
            parts.append(content)
        return "\n\n".join(parts).strip()

    def _validate_supplement(
        self, text: str, base_text: str, reasons: Sequence[str]
    ) -> tuple[bool, str]:
        normalized = _normalize_text(text)
        if len(normalized) < 40:
            return False, "recognized content is too short"
        if "cis_summary_table" in reasons:
            required = {"ig1", "ig2", "ig3", "safeguards", "total"}
            if not required.issubset(set(_WORD_RE.findall(text.lower()))):
                return False, "CIS summary labels were not preserved"

        base_normalized = _normalize_text(base_text)
        if len(base_normalized) >= self.config.min_text_chars:
            candidate_tokens = set(_WORD_RE.findall(normalized))
            source_tokens = set(_WORD_RE.findall(base_normalized))
            overlap = len(candidate_tokens & source_tokens) / max(len(candidate_tokens), 1)
            if overlap < self.config.min_source_overlap:
                return (
                    False,
                    f"source-token overlap {overlap:.2f} is below the safety threshold",
                )
        return True, "accepted"

    @staticmethod
    def _is_redundant(candidate: str, base_text: str) -> bool:
        left = _normalize_text(candidate)
        right = _normalize_text(base_text)
        if not left or not right:
            return False
        if left in right:
            return True
        length_ratio = min(len(left), len(right)) / max(len(left), len(right))
        return length_ratio >= 0.75 and SequenceMatcher(None, left, right).ratio() >= 0.97

    def _cache_path(self, pdf_digest: str, page_number: int) -> Path:
        model_digest = hashlib.sha256(self.config.model_name.encode("utf-8")).hexdigest()[:12]
        return (
            Path(self.config.cache_dir)
            / pdf_digest[:16]
            / f"{model_digest}-dpi{self.config.dpi}-page{page_number:04d}.json"
        )

    def _read_cache(self, path: Path) -> list[dict[str, Any]] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable MinerU cache entry %s.", path)
            return None
        if (
            payload.get("schema_version") != _CACHE_SCHEMA_VERSION
            or payload.get("model_name") != self.config.model_name
            or payload.get("dpi") != self.config.dpi
        ):
            return None
        blocks = payload.get("blocks")
        return blocks if isinstance(blocks, list) else None

    def _write_cache(
        self,
        path: Path,
        pdf_digest: str,
        page_number: int,
        blocks: list[dict[str, Any]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "pdf_sha256": pdf_digest,
            "page_number": page_number,
            "model_name": self.config.model_name,
            "dpi": self.config.dpi,
            "blocks": blocks,
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(path)

    def unload(self) -> None:
        """Release the VLM before Ollama embedding starts."""
        was_loaded = self.model_loaded
        self._client = None
        self._processor = None
        self._model = None
        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
            self._torch.cuda.synchronize()
        self._torch = None
        if was_loaded:
            logger.info("MinerU2.5 model unloaded and accelerator cache released.")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
