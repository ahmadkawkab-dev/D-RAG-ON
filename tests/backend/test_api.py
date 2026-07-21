from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from backend.api.deps import (
    get_chat_service,
    get_current_user,
    get_db,
    get_llm_service,
    get_rag_service,
)
from backend.core.config import Settings
from backend.main import create_app
from backend.models.user import UserDocument
from backend.schemas.chat import Citation
from backend.services.rag_service import RetrievedContext
from tests.backend.fakes import FakeDatabase


def test_auth_register_login_refresh_and_protection() -> None:
    database = FakeDatabase()
    settings = Settings(
        environment="test",
        connect_external_services_on_startup=False,
        jwt_secret_key="test-secret-key-that-is-longer-than-32-bytes",
    )
    application = create_app(settings)
    application.dependency_overrides[get_db] = lambda: database

    with TestClient(application) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": "Person@Example.com",
                "password": "long-password",
                "full_name": "Test Person",
            },
        )
        assert registration.status_code == 201
        assert registration.json()["email"] == "person@example.com"
        assert "hashed_password" not in registration.json()

        duplicate = client.post(
            "/api/v1/auth/register",
            json={
                "email": "person@example.com",
                "password": "long-password",
                "full_name": "Test Person",
            },
        )
        assert duplicate.status_code == 409

        login = client.post(
            "/api/v1/auth/login",
            data={
                "username": "person@example.com",
                "password": "long-password",
            },
        )
        assert login.status_code == 200
        tokens = login.json()
        assert tokens["token_type"] == "bearer"
        assert tokens["access_token"] != tokens["refresh_token"]

        refresh = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refresh.status_code == 200
        assert refresh.json()["access_token"] != tokens["access_token"]

        missing_token = client.get("/api/v1/history/sessions")
        assert missing_token.status_code == 401

        wrong_token_type = client.get(
            "/api/v1/history/sessions",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
        assert wrong_token_type.status_code == 401


class FakeChatService:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def get_or_create_session(self, **kwargs):
        return type("Session", (), {"id": kwargs.get("session_id") or "session-1"})()

    async def append_message(self, **kwargs):
        self.messages.append(kwargs)


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


def test_chat_stream_orders_events_and_persists_sources() -> None:
    settings = Settings(
        environment="test",
        connect_external_services_on_startup=False,
        jwt_secret_key="test-secret-key-that-is-longer-than-32-bytes",
    )
    application = create_app(settings)
    chat_service = FakeChatService()
    user = UserDocument.create(
        email="person@example.com",
        hashed_password="not-returned",
        full_name="Person",
    )
    application.dependency_overrides[get_current_user] = lambda: user
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
    assert chat_service.messages[1]["sources"][0]["page_number"] == 5
