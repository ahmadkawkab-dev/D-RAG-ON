from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from mineru_parser import (
    MinerU2_5Assistant,
    MinerUConfig,
    html_table_to_markdown,
    parse_page_spec,
)
from parse import Chunk, ChunkMetadata, PipelineConfig


def _base_chunk(source: str, text: str, page: int = 1) -> Chunk:
    return Chunk(
        text=text,
        metadata=ChunkMetadata(
            source_file=source,
            doc_title="Test document",
            chunk_id="base-0001",
            chunk_index=0,
            page_start=page,
            page_end=page,
            breadcrumb=("Test",),
            clause_number=None,
            token_count=50,
            element_type="narrative",
        ),
    )


def test_parse_page_spec_normalizes_ranges() -> None:
    assert parse_page_spec("7, 2, 4-6,5") == (2, 4, 5, 6, 7)
    assert parse_page_spec("") == ()


@pytest.mark.parametrize("value", ["0", "3-2", "x", "2-x"])
def test_parse_page_spec_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_page_spec(value)


def test_html_table_is_preserved_as_markdown() -> None:
    html = (
        "<table><tr><th>Group</th><th>Total</th></tr>"
        "<tr><td>IG1</td><td>56</td></tr></table>"
    )
    assert html_table_to_markdown(html) == (
        "| Group | Total |\n"
        "| --- | --- |\n"
        "| IG1 | 56 |"
    )


def test_blocks_are_read_in_visual_order_and_tables_are_structured() -> None:
    blocks = [
        {"type": "text", "bbox": [0, 100, 20, 120], "content": "Second"},
        {
            "type": "table",
            "bbox": [0, 50, 20, 80],
            "content": "<table><tr><td>IG1</td><td>56</td></tr></table>",
        },
    ]
    text = MinerU2_5Assistant.blocks_to_text(blocks)
    assert text.startswith("| IG1 | 56 |")
    assert text.endswith("Second")


def test_selective_mode_targets_cis_summary_and_forced_pages() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "SAFEGUARDS TOTAL IG1 IG2 IG3 controls implementation groups summary table",
    )
    assistant = MinerU2_5Assistant(
        MinerUConfig(
            mode="selective",
            pages=(1,),
            max_pages=4,
            min_text_chars=10,
        )
    )
    try:
        selected = assistant.select_pages(document)
    finally:
        document.close()

    assert len(selected) == 1
    assert set(selected[0].reasons) == {"explicit_page", "cis_summary_table"}


def test_supplement_chunks_leave_base_chunk_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "controls.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "SAFEGUARDS TOTAL IG1 IG2 IG3 inventory controls devices applications network users",
    )
    document.save(pdf_path)
    document.close()

    source_text = (
        "SAFEGUARDS TOTAL IG1 IG2 IG3 inventory controls devices applications "
        "network users implementation security groups"
    )
    base = _base_chunk(pdf_path.name, source_text)
    assistant = MinerU2_5Assistant(
        MinerUConfig(
            mode="selective",
            pages=(1,),
            cache_dir=tmp_path / "cache",
            min_text_chars=10,
            min_source_overlap=0.20,
        )
    )
    extracted = [
        {
            "type": "table",
            "bbox": [0, 0, 100, 100],
            "content": (
                "<table><tr><th>SAFEGUARDS TOTAL</th><th>IG1</th><th>IG2</th><th>IG3</th></tr>"
                "<tr><td>inventory controls</td><td>devices</td><td>applications</td>"
                "<td>network users implementation security groups</td></tr>"
                "<tr><td>Foundational</td><td>56 safeguards</td><td>essential cyber hygiene</td>"
                "<td>applies across enterprise assets</td></tr>"
                "<tr><td>Advanced</td><td>153 safeguards</td><td>risk based program</td><td>total</td></tr></table>"
            ),
        }
    ]
    monkeypatch.setattr(assistant, "_extract_page", lambda *_args: extracted)

    supplements = assistant.supplement_chunks(
        pdf_path, [base], PipelineConfig(min_tokens=1)
    )

    assert base.metadata.chunk_id == "base-0001"
    assert len(supplements) == 1
    assert supplements[0].metadata.element_type == "mineru_visual_supplement"
    assert supplements[0].metadata.chunk_id == "controls-mineru-page0001-part01"
    assert supplements[0].metadata.page_start == 1


