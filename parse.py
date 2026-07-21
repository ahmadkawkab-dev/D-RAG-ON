from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Iterator, Optional

import fitz  # pymupdf
import tiktoken


logger = logging.getLogger("data/CIS_Controls__v8__Critical_Security_Controls__2023_08.pdf")


def configure_logging(verbose: bool = False) -> None:
    """Attach a simple stream handler. Safe to call multiple times."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# Parser settings used by every stage.


@dataclass(frozen=True)
class PipelineConfig:
    """All tunables live here so the pipeline is testable and reusable
    across document types without touching the extraction logic."""

    # Chunk limits are counted with tokens so they match model context limits.
    max_tokens: int = 400          
    min_tokens: int = 40           
    overlap_tokens: int = 60       
    encoding_name: str = "cl100k_base"

    # These values help identify headings from the PDF font layout.
    clause_pattern: str = r"^(\d{1,2}\.\d{1,2})\s+([A-Z][^\n]{2,120})$"
    heading_size_ratio: float = 1.15   
    heading_max_chars: int = 120       

    # Repeated text near page edges is treated as a header or footer.
    boilerplate_page_frequency: float = 0.20
    boilerplate_min_page_count: int = 4

    # OCR is optional and is only used when a page has very little text.
    ocr_enabled: bool = True
    ocr_min_chars: int = 30            
    ocr_dpi: int = 300
    ocr_lang: str = "eng"

    # These labels identify implementation-group columns in checklist tables.
    table_column_labels: tuple[str, ...] = ("IG1", "IG2", "IG3")
    table_column_tolerance_pt: float = 12.0



def load_pipeline_config(path: Path) -> PipelineConfig:
    """Load a complete, versioned parser configuration from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    values = payload.get("pipeline_config", payload)
    if "table_column_labels" in values:
        values["table_column_labels"] = tuple(values["table_column_labels"])
    known = {item.name for item in __import__("dataclasses").fields(PipelineConfig)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown parser configuration fields: {sorted(unknown)}")
    missing = known - set(values)
    if missing:
        raise ValueError(f"Frozen parser configuration is incomplete: {sorted(missing)}")
    return PipelineConfig(**values)

# These data classes keep extracted lines, metadata, and chunks consistent.


@dataclass
class Line:
    """One visually-coherent line of text plus the layout metadata needed
    for heading detection, column ordering, and boilerplate filtering."""
    text: str
    page_number: int          
    font_size: float
    is_bold: bool
    x0: float
    y0: float
    is_horizontal: bool       


@dataclass
class SafeguardAnnotation:
    """Structured fields recovered from a checklist-style table row."""
    clause_number: str
    asset_type: Optional[str] = None
    security_function: Optional[str] = None
    applicable_groups: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class ChunkMetadata:
    source_file: str
    doc_title: str
    chunk_id: str
    chunk_index: int
    page_start: int
    page_end: int
    breadcrumb: tuple[str, ...]        
    clause_number: Optional[str]       
    token_count: int
    element_type: str                  
    table_annotation: Optional[SafeguardAnnotation] = None

    def to_json(self) -> dict:
        d = asdict(self)
        d["breadcrumb"] = list(self.breadcrumb)
        if self.table_annotation is not None:
            d["table_annotation"]["applicable_groups"] = list(
                self.table_annotation.applicable_groups
            )
        return d


@dataclass
class Chunk:
    text: str
    metadata: ChunkMetadata


# Step 1: Read text and layout information from each PDF page.


class PDFTextExtractor:
    """Wraps a fitz.Document and yields ordered `Line` objects per page."""

    def __init__(self, path: Path, config: PipelineConfig):
        self._path = path
        self._config = config
        self._doc: Optional[fitz.Document] = None

    def __enter__(self) -> "PDFTextExtractor":
        try:
            self._doc = fitz.open(self._path)
        except Exception as exc:  
            raise IOError(f"Could not open PDF at {self._path!s}: {exc}") from exc
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._doc is not None:
            self._doc.close()

    @property
    def document(self) -> fitz.Document:
        if self._doc is None:
            raise RuntimeError("PDFTextExtractor must be used as a context manager.")
        return self._doc

    @property
    def title(self) -> str:
        meta_title = (self._doc.metadata or {}).get("title") if self._doc else None
        return meta_title.strip() if meta_title else self._path.stem

    def iter_pages(self) -> Iterator[tuple[int, list[Line], dict]]:
        for index, page in enumerate(self.document):
            page_number = index + 1
            try:
                raw = page.get_text("dict", sort=True)
            except Exception as exc:
                logger.warning("Page %d: text extraction failed (%s); skipping.", page_number, exc)
                continue

            lines = self._lines_from_dict(raw, page_number)
            char_count = sum(len(ln.text) for ln in lines)

            looks_scanned = char_count < self._config.ocr_min_chars and bool(page.get_images())
            if looks_scanned:
                ocr_text = self._maybe_ocr(page, page_number)
                if ocr_text:
                    lines = [
                        Line(
                            text=ocr_text,
                            page_number=page_number,
                            font_size=10.0,
                            is_bold=False,
                            x0=0.0,
                            y0=0.0,
                            is_horizontal=True,
                        )
                    ]

            ordered = self._order_by_columns(lines)
            ordered = self._merge_bare_clause_numbers(ordered)
            yield page_number, ordered, raw

    _BARE_CLAUSE_NUMBER = re.compile(r"^\d{1,2}\.\d{1,2}$")

    @classmethod
    def _merge_bare_clause_numbers(cls, lines: list[Line]) -> list[Line]:
        merged: list[Line] = []
        i = 0
        while i < len(lines):
            current = lines[i]
            if cls._BARE_CLAUSE_NUMBER.match(current.text) and i + 1 < len(lines):
                nxt = lines[i + 1]
                merged.append(
                    Line(
                        text=f"{current.text} {nxt.text}",
                        page_number=current.page_number,
                        font_size=nxt.font_size,
                        is_bold=nxt.is_bold,
                        x0=current.x0,
                        y0=current.y0,
                        is_horizontal=True,
                    )
                )
                i += 2
                continue
            merged.append(current)
            i += 1
        return merged

    @staticmethod
    def _lines_from_dict(raw: dict, page_number: int) -> list[Line]:
        lines: list[Line] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0: 
                continue
            for line in block.get("lines", []):
                direction = line.get("dir", (1.0, 0.0))
                is_horizontal = abs(direction[0]) > 0.5
                
                valid_spans = []
                for s in line.get("spans", []):
                    txt = s.get("text", "")
                    if not txt.strip():
                        continue
                    sb = s.get("bbox", (0, 0, 0, 0))
                    is_overlap = False
                    for vs in valid_spans:
                        vsb = vs.get("bbox", (0, 0, 0, 0))
                        x_overlap = max(0, min(sb[2], vsb[2]) - max(sb[0], vsb[0]))
                        y_overlap = max(0, min(sb[3], vsb[3]) - max(sb[1], vsb[1]))
                        if x_overlap > 0 and y_overlap > 0:
                            s_area = (sb[2] - sb[0]) * (sb[3] - sb[1])
                            vs_area = (vsb[2] - vsb[0]) * (vsb[3] - vsb[1])
                            min_area = min(s_area, vs_area)
                            if min_area > 0 and (x_overlap * y_overlap) / min_area > 0.70:
                                if len(txt.strip()) <= len(vs.get("text", "").strip()):
                                    is_overlap = True
                                    break
                                else:
                                    valid_spans.remove(vs)
                                    break
                    if not is_overlap:
                        valid_spans.append(s)

                if not valid_spans:
                    continue

                text = "".join(s["text"] for s in valid_spans).strip()
                if not text:
                    continue

                size_char_mass: dict[float, int] = {}
                for s in valid_spans:
                    size = round(s.get("size", 10.0), 1)
                    size_char_mass[size] = size_char_mass.get(size, 0) + len(s["text"])
                dominant_size = max(size_char_mass.items(), key=lambda kv: kv[1])[0]
                dominant_span = max(
                    (s for s in valid_spans if round(s.get("size", 10.0), 1) == dominant_size),
                    key=lambda s: len(s["text"]),
                )
                lines.append(
                    Line(
                        text=text,
                        page_number=page_number,
                        font_size=dominant_size,
                        is_bold=bool(dominant_span.get("flags", 0) & 2 ** 4)
                        or "Bold" in dominant_span.get("font", ""),
                        x0=line["bbox"][0],
                        y0=line["bbox"][1],
                        is_horizontal=is_horizontal,
                    )
                )

        cleaned_lines: list[Line] = []
        for ln in lines:
            is_duplicate = False
            for existing in cleaned_lines:
                if abs(ln.x0 - existing.x0) < 1.5 and abs(ln.y0 - existing.y0) < 1.5:
                    if len(ln.text) <= len(existing.text):
                        is_duplicate = True
                        break
                    else:
                        cleaned_lines.remove(existing)
                        break
            if not is_duplicate:
                cleaned_lines.append(ln)

        return [ln for ln in cleaned_lines if ln.is_horizontal]

    @staticmethod
    def _order_by_columns(lines: list[Line], gap_threshold: float = 50.0) -> list[Line]:
        if not lines:
            return lines
        xs = sorted({round(ln.x0) for ln in lines})
        clusters: list[list[float]] = [[xs[0]]]
        for x in xs[1:]:
            if x - clusters[-1][-1] > gap_threshold:
                clusters.append([x])
            else:
                clusters[-1].append(x)
        boundaries = [min(c) for c in clusters] + [float("inf")]

        def column_of(x0: float) -> int:
            for i in range(len(boundaries) - 1):
                if boundaries[i] <= x0 < boundaries[i + 1]:
                    return i
            return len(boundaries) - 2

        if len(clusters) <= 1:
            return sorted(lines, key=lambda ln: ln.y0)

        row_aligned_count = 0
        for i, ln1 in enumerate(lines):
            col1 = column_of(ln1.x0)
            for ln2 in lines[i + 1:]:
                col2 = column_of(ln2.x0)
                if col1 != col2 and abs(ln1.y0 - ln2.y0) < 4.0:
                    row_aligned_count += 1
                    break

        if row_aligned_count > len(lines) * 0.20:
            sorted_by_y = sorted(lines, key=lambda ln: ln.y0)
            ordered_lines = []
            while sorted_by_y:
                base_line = sorted_by_y[0]
                row_lines = [ln for ln in sorted_by_y if abs(ln.y0 - base_line.y0) < 4.0]
                row_lines.sort(key=lambda ln: ln.x0)  
                ordered_lines.extend(row_lines)
                sorted_by_y = [ln for ln in sorted_by_y if ln not in row_lines]
            return ordered_lines
        else:
            return sorted(lines, key=lambda ln: (column_of(ln.x0), ln.y0))

    def _maybe_ocr(self, page: fitz.Page, page_number: int) -> Optional[str]:
        if not self._config.ocr_enabled:
            return None
        if shutil.which("tesseract") is None:
            return None
        try:
            import pytesseract  
            from PIL import Image
        except ImportError:
            return None

        pix = page.get_pixmap(dpi=self._config.ocr_dpi)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        try:
            return pytesseract.image_to_string(image, lang=self._config.ocr_lang).strip()
        except Exception:
            return None


# Step 2: Remove headers and footers that repeat across pages.


class BoilerplateFilter:
    """Removes lines that repeat across many pages, strictly isolated to top/bottom margins."""

    _DIGITS = re.compile(r"\d+")

    def __init__(self, config: PipelineConfig):
        self._config = config

    def fit(self, pages: list[list[Line]]) -> set[str]:
        total_pages = len(pages)
        counts: dict[str, int] = {}
        for lines in pages:
            seen_this_page: set[str] = set()
            for ln in lines:
                # Only inspect page edges so normal body text is not removed.
                if ln.y0 < 70 or ln.y0 > 750:
                    key = self._normalize(ln.text)
                    if key and key not in seen_this_page:
                        counts[key] = counts.get(key, 0) + 1
                        seen_this_page.add(key)

        threshold = max(
            self._config.boilerplate_min_page_count,
            int(total_pages * self._config.boilerplate_page_frequency),
        )
        boilerplate = {k for k, c in counts.items() if c >= threshold}
        logger.info("Detected %d recurring header/footer line pattern(s).", len(boilerplate))
        return boilerplate

    def apply(self, lines: list[Line], boilerplate: set[str]) -> list[Line]:
        return [
            ln for ln in lines 
            if not ((ln.y0 < 70 or ln.y0 > 750) and self._normalize(ln.text) in boilerplate)
        ]

    @classmethod
    def _normalize(cls, text: str) -> str:
        return cls._DIGITS.sub("#", text).strip().lower()


# Step 3: Build a heading hierarchy from font sizes and numbering.


@dataclass
class Heading:
    text: str
    level: int          
    page_number: int


class HeadingClassifier:
    def __init__(self, config: PipelineConfig):
        self._config = config
        self._body_size: float = 10.0
        self._level_sizes: list[float] = []

    _MIN_CHAR_MASS_PER_TIER = 15

    def fit(self, pages: list[list[Line]]) -> None:
        all_lines = [ln for lines in pages for ln in lines]
        if not all_lines:
            return
        self._body_size = statistics.mode(round(ln.font_size) for ln in all_lines)

        char_mass_by_size: dict[float, int] = {}
        for ln in all_lines:
            if ln.font_size >= self._body_size * self._config.heading_size_ratio:
                char_mass_by_size[ln.font_size] = char_mass_by_size.get(ln.font_size, 0) + len(ln.text)

        heading_sizes = sorted(
            (size for size, mass in char_mass_by_size.items() if mass >= self._MIN_CHAR_MASS_PER_TIER),
            reverse=True,
        )
        self._level_sizes = heading_sizes

    def classify(self, line: Line) -> Optional[int]:
        if len(line.text) > self._config.heading_max_chars:
            return None
        if not re.search(r"[A-Za-z]", line.text):
            return None
        if line.font_size < self._body_size * self._config.heading_size_ratio:
            return None
        for level, size in enumerate(self._level_sizes, start=1):
            if abs(line.font_size - size) < 0.5:
                return level
        return None


# Step 4: Read checklist columns and attach their values to safeguards.


class ChecklistTableParser:
    def __init__(self, config: PipelineConfig):
        self._config = config
        self._clause_re = re.compile(r"^\d{1,2}\.\d{1,2}$")

    def parse_document(self, doc: fitz.Document) -> dict[str, SafeguardAnnotation]:
        annotations: dict[str, SafeguardAnnotation] = {}
        for page in doc:
            raw = page.get_text("dict", sort=True)
            annotations.update(self._parse_page(raw))
        return annotations

    def _parse_page(self, raw: dict) -> dict[str, SafeguardAnnotation]:
        spans_by_line: list[list[dict]] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s["text"].strip()]
                if spans:
                    spans_by_line.append(spans)

        column_x: dict[str, float] = {}
        for spans in spans_by_line:
            for s in spans:
                token = s["text"].strip()
                if token in self._config.table_column_labels:
                    column_x[token] = s["bbox"][0]

        if not column_x:
            return {}

        results: dict[str, SafeguardAnnotation] = {}
        current: Optional[SafeguardAnnotation] = None
        tol = self._config.table_column_tolerance_pt

        for spans in spans_by_line:
            first_text = spans[0]["text"].strip()
            if self._clause_re.match(first_text):
                current = SafeguardAnnotation(clause_number=first_text)
                results[first_text] = current
                continue
            if current is None:
                continue
            for s in spans:
                token = s["text"].strip()
                if token == "\u2022":
                    x0 = s["bbox"][0]
                    for label, cx in column_x.items():
                        if abs(x0 - cx) <= tol:
                            current.applicable_groups = tuple(
                                sorted(set(current.applicable_groups) | {label})
                            )
                elif token in {"Devices", "Data", "Applications", "Network", "Users", "N/A"}:
                    current.asset_type = token
                elif token.startswith("-") and token.endswith("-"):
                    current.security_function = token.strip("-")
        return results


# Step 5: Split each section into model-sized semantic chunks.


class TokenCounter:
    _CHARS_PER_TOKEN_ESTIMATE = 4.0

    def __init__(self, encoding_name: str):
        self._enc = None
        try:
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception:
            pass

    def count(self, text: str) -> int:
        if self._enc is not None:
            return len(self._enc.encode(text))
        return max(1, int(len(text) / self._CHARS_PER_TOKEN_ESTIMATE))

    def truncate_with_overlap(self, text: str, max_tokens: int, overlap: int) -> list[str]:
        if self._enc is not None:
            tokens = self._enc.encode(text)
            if len(tokens) <= max_tokens:
                return [text]
            pieces = []
            start = 0
            step = max(1, max_tokens - overlap)
            while start < len(tokens):
                piece = tokens[start : start + max_tokens]
                pieces.append(self._enc.decode(piece))
                start += step
            return pieces

        max_chars = int(max_tokens * self._CHARS_PER_TOKEN_ESTIMATE)
        overlap_chars = int(overlap * self._CHARS_PER_TOKEN_ESTIMATE)
        if len(text) <= max_chars:
            return [text]
        pieces = []
        start = 0
        step = max(1, max_chars - overlap_chars)
        while start < len(text):
            pieces.append(text[start : start + max_chars])
            start += step
        return pieces


class SemanticChunker:
    _SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

    def __init__(self, config: PipelineConfig, token_counter: TokenCounter):
        self._config = config
        self._tokens = token_counter
        self._clause_re = re.compile(config.clause_pattern, re.MULTILINE)

    def chunk_section(
        self,
        text: str,
        breadcrumb: tuple[str, ...],
        page_start: int,
        page_end: int,
        table_annotations: dict[str, SafeguardAnnotation],
    ) -> list[tuple[str, str, Optional[str], Optional[SafeguardAnnotation]]]:
        clause_pieces = self._split_by_clause(text)
        results: list[tuple[str, str, Optional[str], Optional[SafeguardAnnotation]]] = []

        for clause_number, piece_text in clause_pieces:
            element_type = "clause" if clause_number else "narrative"
            annotation = table_annotations.get(clause_number) if clause_number else None

            if annotation and annotation.applicable_groups:
                front_matter = (
                    f"[Applies to Implementation Groups: "
                    f"{', '.join(annotation.applicable_groups)}"
                    f"{'; Asset Type: ' + annotation.asset_type if annotation.asset_type else ''}"
                    f"{'; Security Function: ' + annotation.security_function if annotation.security_function else ''}]"
                )
                piece_text = f"{front_matter}\n{piece_text}"

            token_count = self._tokens.count(piece_text)
            if token_count <= self._config.max_tokens:
                results.append((piece_text, element_type, clause_number, annotation))
                continue

            for sub in self._split_oversized(piece_text):
                results.append((sub, element_type, clause_number, annotation))

        return self._merge_undersized(results)

    def _split_by_clause(self, text: str) -> list[tuple[Optional[str], str]]:
        matches = list(self._clause_re.finditer(text))
        if not matches:
            return [(None, text.strip())] if text.strip() else []

        pieces: list[tuple[Optional[str], str]] = []
        preamble = text[: matches[0].start()].strip()
        if preamble:
            pieces.append((None, preamble))

        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start() : end].strip()
            pieces.append((m.group(1), body))
        return pieces

    def _split_oversized(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        if len(paragraphs) <= 1:
            paragraphs = self._SENTENCE_SPLIT.split(text)

        chunks: list[str] = []
        buffer: list[str] = []
        buffer_tokens = 0

        def flush() -> None:
            if buffer:
                chunks.append(" ".join(buffer).strip())

        for para in paragraphs:
            para_tokens = self._tokens.count(para)
            if para_tokens > self._config.max_tokens:
                flush()
                buffer, buffer_tokens = [], 0
                chunks.extend(
                    self._tokens.truncate_with_overlap(
                        para, self._config.max_tokens, self._config.overlap_tokens
                    )
                )
                continue
            if buffer_tokens + para_tokens > self._config.max_tokens:
                flush()
                overlap_text = buffer[-1] if buffer else ""
                buffer = [overlap_text] if overlap_text else []
                buffer_tokens = self._tokens.count(overlap_text) if overlap_text else 0
            buffer.append(para)
            buffer_tokens += para_tokens
        flush()
        return [c for c in chunks if c]

    def _merge_undersized(
        self, pieces: list[tuple[str, str, Optional[str], Optional[SafeguardAnnotation]]]
    ) -> list[tuple[str, str, Optional[str], Optional[SafeguardAnnotation]]]:
        merged: list[tuple[str, str, Optional[str], Optional[SafeguardAnnotation]]] = []
        for text, etype, clause, annotation in pieces:
            if (
                merged
                and self._tokens.count(text) < self._config.min_tokens
                and merged[-1][2] == clause
            ):
                prev_text, prev_etype, prev_clause, prev_ann = merged[-1]
                merged[-1] = (f"{prev_text}\n{text}", prev_etype, prev_clause, prev_ann)
            else:
                merged.append((text, etype, clause, annotation))
        return merged


# Step 6: Run every parsing stage and assemble the final chunks.


class PDFChunkingPipeline:
    def __init__(self, config: Optional[PipelineConfig] = None):
        self._config = config or PipelineConfig()
        self._tokens = TokenCounter(self._config.encoding_name)

    def run(self, pdf_path: Path) -> list[Chunk]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"No such file: {pdf_path}")

        logger.info("Opening %s", pdf_path.name)
        with PDFTextExtractor(pdf_path, self._config) as extractor:
            page_lines: list[list[Line]] = []
            page_numbers: list[int] = []
            for page_number, lines, _raw in extractor.iter_pages():
                page_lines.append(lines)
                page_numbers.append(page_number)

            boilerplate_filter = BoilerplateFilter(self._config)
            boilerplate = boilerplate_filter.fit(page_lines)
            page_lines = [boilerplate_filter.apply(lines, boilerplate) for lines in page_lines]

            heading_classifier = HeadingClassifier(self._config)
            heading_classifier.fit(page_lines)

            table_parser = ChecklistTableParser(self._config)
            table_annotations = table_parser.parse_document(extractor.document)

            doc_title = extractor.title
            sections = self._build_sections(page_lines, page_numbers, heading_classifier)

        chunker = SemanticChunker(self._config, self._tokens)
        chunks: list[Chunk] = []
        chunk_index = 0

        for breadcrumb, page_start, page_end, text in sections:
            for piece_text, etype, clause, annotation in chunker.chunk_section(
                text, breadcrumb, page_start, page_end, table_annotations
            ):
                if not piece_text.strip():
                    continue
                metadata = ChunkMetadata(
                    source_file=pdf_path.name,
                    doc_title=doc_title,
                    chunk_id=f"{pdf_path.stem}-{chunk_index:04d}",
                    chunk_index=chunk_index,
                    page_start=page_start,
                    page_end=page_end,
                    breadcrumb=breadcrumb,
                    clause_number=clause,
                    token_count=self._tokens.count(piece_text),
                    element_type=etype,
                    table_annotation=annotation,
                )
                chunks.append(Chunk(text=piece_text, metadata=metadata))
                chunk_index += 1

        chunks = self._merge_global_chunks(chunks)

        self._assign_unique_semantic_ids(chunks)
        logger.info("Produced %d chunks from %d pages.", len(chunks), len(page_numbers))
        return chunks


    def _assign_unique_semantic_ids(self, chunks: list[Chunk]) -> None:
        """Assign stable semantic IDs without overwriting duplicate passages."""
        occurrences: dict[str, int] = {}
        for chunk in chunks:
            base_id = self._generate_semantic_id(
                chunk.metadata, chunk.metadata.chunk_id
            )
            occurrence = occurrences.get(base_id, 0) + 1
            occurrences[base_id] = occurrence
            chunk.metadata.chunk_id = (
                base_id if occurrence == 1 else f"{base_id}-part{occurrence:02d}"
            )

    def _generate_semantic_id(self, metadata: ChunkMetadata, default_id: str) -> str:
        """Derives a semantic chunk ID based on the content (matching the golden dataset structure)."""
        if metadata.clause_number:
            parts = metadata.clause_number.split('.')
            if len(parts) >= 2 and parts[0].isdigit():
                return f"control{int(parts[0]):02d}-safeguard{metadata.clause_number}"
        
        bc_str = " | ".join(metadata.breadcrumb).lower()
        if "glossary" in bc_str:
            return f"glossary-{default_id.split('-')[-1]}"
        
        match = re.search(r"control\s+(\d+)", bc_str)
        if match:
            cnum = int(match.group(1))
            if "safeguard" not in bc_str:
                return f"control{cnum:02d}-overview"

        if "introduction" in bc_str or "overview" in bc_str:
            return f"intro-{default_id.split('-')[-1]}"
            
        return default_id

    def _merge_global_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return chunks
        final_chunks: list[Chunk] = []
        for chunk in chunks:
            if final_chunks and (
                final_chunks[-1].metadata.token_count < self._config.min_tokens 
                or chunk.metadata.token_count < self._config.min_tokens
            ):
                prev = final_chunks[-1]
                combined_text = f"{prev.text}\n{chunk.text}"
                combined_tokens = self._tokens.count(combined_text)
                if combined_tokens <= self._config.max_tokens:
                    prev.text = combined_text
                    prev.metadata.page_end = max(prev.metadata.page_end, chunk.metadata.page_end)
                    prev.metadata.token_count = combined_tokens
                    if len(prev.metadata.breadcrumb) < len(chunk.metadata.breadcrumb) or not prev.metadata.clause_number:
                        prev.metadata.breadcrumb = chunk.metadata.breadcrumb
                        prev.metadata.clause_number = chunk.metadata.clause_number
                        prev.metadata.element_type = chunk.metadata.element_type
                        prev.metadata.table_annotation = chunk.metadata.table_annotation
                    continue
            final_chunks.append(chunk)
        
        for idx, chunk in enumerate(final_chunks):
            chunk.metadata.chunk_index = idx
            
        return final_chunks

    def _build_sections(
        self,
        page_lines: list[list[Line]],
        page_numbers: list[int],
        heading_classifier: HeadingClassifier,
    ) -> list[tuple[tuple[str, ...], int, int, str]]:
        sections: list[tuple[tuple[str, ...], int, int, str]] = []
        stack: list[tuple[int, str]] = []
        buffer: list[str] = []
        page_start: Optional[int] = None
        page_end: Optional[int] = None

        def flush() -> None:
            nonlocal buffer, page_start, page_end
            body = "\n".join(buffer).strip()
            if body and page_start is not None:
                breadcrumb = tuple(text for _, text in stack)
                sections.append((breadcrumb, page_start, page_end or page_start, body))
            buffer = []
            page_start = None
            page_end = None

        for lines, page_number in zip(page_lines, page_numbers):
            for line in lines:
                level = heading_classifier.classify(line)
                if level is not None:
                    if stack and stack[-1][0] == level and not buffer:
                        prev_level, prev_text = stack[-1]
                        stack[-1] = (prev_level, f"{prev_text} {line.text}".strip())
                        continue
                    flush()
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    stack.append((level, line.text))
                    continue
                buffer.append(line.text)
                page_start = page_start or page_number
                page_end = page_number
        flush()
        return sections


# Save parsed chunks in the JSONL format used by ingestion and evaluation.


def write_jsonl(chunks: Iterable[Chunk], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            record = {"text": chunk.text, "metadata": chunk.metadata.to_json()}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("Wrote chunks to %s", out_path)


# This command-line entry point lets the parser run without either UI.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path, help="Path to the input PDF.")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("chunks.jsonl"), help="Output JSONL path."
    )
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--overlap-tokens", type=int, default=60)
    parser.add_argument(
        "--parser-config", type=Path, default=None,
        help="Complete frozen parser JSON; overrides chunking flags",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)
    config = (
        load_pipeline_config(args.parser_config)
        if args.parser_config
        else PipelineConfig(max_tokens=args.max_tokens, overlap_tokens=args.overlap_tokens)
    )

    try:
        pipeline = PDFChunkingPipeline(config)
        chunks = pipeline.run(args.pdf_path)
    except (IOError, FileNotFoundError) as exc:
        logger.error("Pipeline aborted: %s", exc)
        raise SystemExit(1) from exc

    write_jsonl(chunks, args.output)

    for chunk in chunks[:3]:
        logger.info(
            "Sample chunk %s | pages %s-%s | breadcrumb=%s | tokens=%d",
            chunk.metadata.chunk_id,
            chunk.metadata.page_start,
            chunk.metadata.page_end,
            " > ".join(chunk.metadata.breadcrumb),
            chunk.metadata.token_count,
        )


if __name__ == "__main__":
    main()