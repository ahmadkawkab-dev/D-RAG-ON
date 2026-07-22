from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.deps import (
    get_chat_service,
    get_current_user,
    get_db,
    get_email_service,
    get_llm_service,
    get_rag_service,
)
from backend.core.config import Settings
from backend.main import create_app
from backend.models.user import UserDocument
from backend.schemas.chat import Citation
from backend.services.rag_service import RetrievedContext
from tests.backend.fakes import FakeDatabase


def test_profile_patch_cors_preflight_allows_local_development_origins() -> None:
    settings = Settings(
        environment="test",
        connect_external_services_on_startup=False,
        jwt_secret_key="test-secret-key-that-is-longer-than-32-bytes",
    )
    application = create_app(settings)

    with TestClient(application) as client:
        response = client.options(
            "/api/v1/users/me",
            headers={
                "Origin": "http://127.0.0.1:5199",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:5199"
    )
    assert "PATCH" in response.headers["access-control-allow-methods"]


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


class FakeEmailService:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int]] = []

    def ensure_available(self) -> None:
        return None

    async def send_password_reset_code(
        self,
        email: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        self.sent.append((email, code, expires_in_minutes))


def test_password_reset_profile_password_change_and_usage() -> None:
    database = FakeDatabase()
    settings = Settings(
        environment="test",
        connect_external_services_on_startup=False,
        jwt_secret_key="test-secret-key-that-is-longer-than-32-bytes",
    )
    application = create_app(settings)
    email_service = FakeEmailService()
    application.dependency_overrides[get_db] = lambda: database
    application.dependency_overrides[get_email_service] = lambda: email_service

    with TestClient(application) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": "profile@example.com",
                "password": "original-password",
                "full_name": "Profile Person",
            },
        )
        assert registration.status_code == 201
        assert registration.json()["avatar_url"] is None

        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "profile@example.com",
                "password": "original-password",
            },
        )
        assert login_response.status_code == 200
        headers = {
            "Authorization": (
                f"Bearer {login_response.json()['access_token']}"
            )
        }

        profile = client.get("/api/v1/users/me", headers=headers)
        assert profile.status_code == 200
        assert profile.json()["full_name"] == "Profile Person"

        avatar = "data:image/png;base64,aGVsbG8="
        updated = client.patch(
            "/api/v1/users/me",
            headers=headers,
            json={"full_name": "Updated Person", "avatar_url": avatar},
        )
        assert updated.status_code == 200
        assert updated.json()["full_name"] == "Updated Person"
        assert updated.json()["avatar_url"] == avatar

        usage = client.get("/api/v1/users/me/usage", headers=headers)
        assert usage.status_code == 200
        assert usage.json() == {
            "conversations": 0,
            "messages": 0,
            "assistant_answers": 0,
            "feedback_submitted": 0,
        }

        wrong_password = client.post(
            "/api/v1/users/me/password",
            headers=headers,
            json={
                "current_password": "wrong-password",
                "new_password": "changed-password",
            },
        )
        assert wrong_password.status_code == 400

        changed = client.post(
            "/api/v1/users/me/password",
            headers=headers,
            json={
                "current_password": "original-password",
                "new_password": "changed-password",
            },
        )
        assert changed.status_code == 200

        reset_request = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "profile@example.com"},
        )
        assert reset_request.status_code == 202
        assert len(email_service.sent) == 1
        email, code, expires = email_service.sent[0]
        assert email == "profile@example.com"
        assert len(code) == 6
        assert expires == settings.password_reset_expire_minutes

        invalid_code = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": email,
                "code": "000000" if code != "000000" else "000001",
                "new_password": "reset-password",
            },
        )
        assert invalid_code.status_code == 400

        reset = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": email,
                "code": code,
                "new_password": "reset-password",
            },
        )
        assert reset.status_code == 200

        login_after_reset = client.post(
            "/api/v1/auth/login",
            data={
                "username": email,
                "password": "reset-password",
            },
        )
        assert login_after_reset.status_code == 200
