from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.deps import (
    get_chat_service,
    get_db,
    get_internal_user_id,
    get_llm_service,
    get_rag_service,
)
from backend.core.config import Settings
from backend.main import create_app
from backend.schemas.chat import Citation
from backend.services.rag_service import RetrievedContext
from tests.backend.fakes import FakeDatabase


INTERNAL_API_KEY = "test-internal-api-key-that-is-at-least-32-characters"


def test_internal_auth_rejects_missing_and_invalid_credentials() -> None:
    application = create_app(
        Settings(
            environment="test",
            connect_external_services_on_startup=False,
            internal_api_key=INTERNAL_API_KEY,
        )
    )

    with TestClient(application) as client:
        missing = client.get("/api/v1/history/sessions")
        invalid = client.get(
            "/api/v1/history/sessions",
            headers={
                "X-RAG-API-Key": "wrong-value-that-is-not-the-configured-secret",
                "X-Application-User-Id": "user-1",
            },
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert INTERNAL_API_KEY not in missing.text
    assert INTERNAL_API_KEY not in invalid.text


def test_internal_auth_accepts_service_key_and_trusted_user_context() -> None:
    database = FakeDatabase()
    application = create_app(
        Settings(
            environment="test",
            connect_external_services_on_startup=False,
            internal_api_key=INTERNAL_API_KEY,
        )
    )
    application.dependency_overrides[get_db] = lambda: database

    with TestClient(application) as client:
        response = client.get(
            "/api/v1/history/sessions",
            headers={
                "X-RAG-API-Key": INTERNAL_API_KEY,
                "X-Application-User-Id": "user-1",
            },
        )

    assert response.status_code == 200
    assert response.json() == []


def test_removed_browser_auth_routes_are_not_exposed() -> None:
    application = create_app(
        Settings(
            environment="test",
            connect_external_services_on_startup=False,
            internal_api_key=INTERNAL_API_KEY,
        )
    )

    with TestClient(application) as client:
        assert client.post("/api/v1/auth/login").status_code == 404
        assert client.post("/api/v1/auth/register").status_code == 404
        assert client.post("/api/v1/auth/refresh").status_code == 404
        assert client.get("/api/v1/users/me").status_code == 404


class FakeChatService:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def get_or_create_session(self, **kwargs):
        return type("Session", (), {"id": kwargs.get("session_id") or "session-1"})()

    async def append_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(
            id=f"message-{len(self.messages)}",
            role=kwargs["role"],
            content=kwargs["content"],
        )

    async def next_version(self, **kwargs):
        return 1


class FakeRAGService:
    @asynccontextmanager
    async def model_execution(self):
        yield

    async def retrieve(self, message: str) -> RetrievedContext:
        chunk = {
            "text": "Grounded evidence",
            "score": 0.8,
            "rerank_score": 0.95,
            "metadata": {"document_id": "doc-1"},
        }
        return RetrievedContext(
            chunks=[chunk],
            sources=[
                Citation(
                    document_id="doc-1",
                    title="CIS Controls",
                    file_path="data/cis.pdf",
                    chunk_text="Grounded evidence",
                    score=0.95,
                    relevance=0.95,
                    page_number=5,
                    section="5.1",
                )
            ],
            is_relevant=True,
        )


class FakeLLMService:
    async def stream_answer(self, question: str, chunks: list[dict]):
        for token in ("Grounded ", "answer"):
            yield token


def test_document_chat_behavior_is_preserved_after_auth_migration() -> None:
    application = create_app(
        Settings(
            environment="test",
            connect_external_services_on_startup=False,
            internal_api_key=INTERNAL_API_KEY,
        )
    )
    chat_service = FakeChatService()
    application.dependency_overrides[get_internal_user_id] = lambda: "user-1"
    application.dependency_overrides[get_chat_service] = lambda: chat_service
    application.dependency_overrides[get_rag_service] = FakeRAGService
    application.dependency_overrides[get_llm_service] = FakeLLMService

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Explain control 5"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert body.index("event: started") < body.index("event: metadata")
    assert body.index("event: metadata") < body.index("event: delta")
    assert body.index("event: delta") < body.index("event: done")
    assert '"document_id":"doc-1"' in body
    assert '"session_id":"session-1"' in body
    assert [message["role"] for message in chat_service.messages] == [
        "user",
        "assistant",
    ]
    assert chat_service.messages[1]["content"] == "Grounded answer"
