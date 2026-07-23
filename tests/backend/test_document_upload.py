from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app
from backend.services.document_ingestion_service import DocumentIngestionService


INTERNAL_API_KEY = "test-internal-api-key-that-is-at-least-32-characters"
INTERNAL_HEADERS = {
    "X-RAG-API-Key": INTERNAL_API_KEY,
    "X-Application-User-Id": "user-1",
}


def application():
    return create_app(
        Settings(
            environment="test",
            connect_external_services_on_startup=False,
            internal_api_key=INTERNAL_API_KEY,
        )
    )


def test_upload_requires_internal_service_credentials() -> None:
    with TestClient(application()) as client:
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", b"%PDF-1.7\n", "application/pdf")},
        )

    assert response.status_code == 401
    assert INTERNAL_API_KEY not in response.text


def test_upload_rejects_non_pdf_before_ingestion(monkeypatch) -> None:
    called = False

    def unexpected_ingestion(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("ingestion should not run")

    monkeypatch.setattr(
        DocumentIngestionService,
        "ingest_pdf",
        unexpected_ingestion,
    )
    with TestClient(application()) as client:
        response = client.post(
            "/api/v1/documents/upload",
            headers=INTERNAL_HEADERS,
            files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        )

    assert response.status_code == 400
    assert called is False


def test_upload_rejects_oversized_pdf(monkeypatch) -> None:
    called = False

    def unexpected_ingestion(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("ingestion should not run")

    monkeypatch.setattr(
        DocumentIngestionService,
        "ingest_pdf",
        unexpected_ingestion,
    )
    oversized = b"%PDF-" + b"x" * (10 * 1024 * 1024)
    with TestClient(application()) as client:
        response = client.post(
            "/api/v1/documents/upload",
            headers=INTERNAL_HEADERS,
            files={"file": ("large.pdf", oversized, "application/pdf")},
        )

    assert response.status_code == 413
    assert called is False


def test_valid_pdf_uses_existing_ingestion_service(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ingestion(self, path, document_id):
        captured["path_name"] = path.name
        captured["document_id"] = document_id
        captured["signature"] = path.read_bytes()[:5]
        return {
            "document_id": document_id,
            "chunk_count": 3,
            "status": "indexed",
        }

    monkeypatch.setattr(
        DocumentIngestionService,
        "ingest_pdf",
        fake_ingestion,
    )
    with TestClient(application()) as client:
        response = client.post(
            "/api/v1/documents/upload",
            headers=INTERNAL_HEADERS,
            files={
                "file": (
                    "customer-filename.pdf",
                    b"%PDF-1.7\nsafe fixture",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "indexed"
    assert payload["chunk_count"] == 3
    assert payload["document_id"] == captured["document_id"]
    assert captured["path_name"] == f"{payload['document_id']}.pdf"
    assert captured["signature"] == b"%PDF-"
    assert "customer-filename" not in response.text
