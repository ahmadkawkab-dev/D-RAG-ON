import json
from pathlib import Path
import parsing_workspace

import background_tasks
import dashboard


def test_query_worker_persists_result_and_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request_path = tmp_path / "query-request.json"
    result_path = tmp_path / "query-result.json"
    request_path.write_text(
        json.dumps(
            {
                "query": "What is required?",
                "configuration": {"answer": True, "top_n": 3},
            }
        ),
        encoding="utf-8",
    )
    emitted: list[str] = []

    def fake_pipeline(query, *, on_line, **configuration):
        assert query == "What is required?"
        assert configuration == {"answer": True, "top_n": 3}
        on_line("[phase 1/3] retrieve")
        emitted.append("called")
        return {"query": query, "answer": "A grounded answer", "ranked": []}

    monkeypatch.setattr(background_tasks, "run_query_pipeline", fake_pipeline)

    background_tasks.run_query(request_path, result_path)

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert emitted == ["called"]
    assert payload["result"]["answer"] == "A grounded answer"
    assert payload["configuration"]["top_n"] == 3
    assert payload["elapsed_seconds"] >= 0


def test_parse_worker_persists_review_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf_path = tmp_path / "document.pdf"
    pdf_path.write_bytes(b"%PDF-background-test")
    request_path = tmp_path / "parse-request.json"
    result_path = tmp_path / "parse-result.json"
    request_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": str(pdf_path),
                        "name": "document.pdf",
                        "sha256": "abc",
                        "page_count": 2,
                    }
                ],
                "configuration": {"max_tokens": 400},
            }
        ),
        encoding="utf-8",
    )

    def fake_parse(file_bytes, file_name, configuration, event_sink):
        assert file_bytes == b"%PDF-background-test"
        assert file_name == "document.pdf"
        assert configuration["max_tokens"] == 400
        event_sink({"event": "stage", "stage": "chunking", "state": "complete"})
        return {
            "file_name": file_name,
            "file_sha256": "abc",
            "processing_time": 0.2,
            "config": configuration,
            "logs": [],
            "stage_reports": [],
            "chunks": [],
        }

    monkeypatch.setattr(parsing_workspace, "run_pipeline_bytes", fake_parse)

    background_tasks.run_parse(request_path, result_path)

    results = json.loads(result_path.read_text(encoding="utf-8"))
    assert results[0]["page_count"] == 2
    assert results[0]["cache_hit"] is False
    assert results[0]["request_time"] >= 0


def test_background_job_priority_is_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(dashboard, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(dashboard.subprocess, "Popen", lambda *args, **kwargs: None)

    meta_path = dashboard.start_background_job(
        "query",
        "Interactive question",
        ["python", "worker.py"],
        priority="interactive",
    )

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["priority"] == "interactive"
    assert metadata["kind"] == "query"
