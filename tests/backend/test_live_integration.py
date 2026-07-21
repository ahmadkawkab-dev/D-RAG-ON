"""Opt-in tests against live MongoDB, Weaviate, Ollama, and local models."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.core.config import Settings
from backend.main import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG_TESTS") != "1",
    reason="set RUN_LIVE_RAG_TESTS=1 to use local services and models",
)


@pytest.fixture
def live_client():
    database_name = f"rag_it_{uuid4().hex[:20]}"
    settings = Settings(
        environment="test",
        mongodb_database=database_name,
        connect_external_services_on_startup=True,
        jwt_secret_key="integration-secret-key-longer-than-32-bytes",
        hybrid_alpha=0.0,
        retrieve_k=50,
    )
    application = create_app(settings)
    try:
        with TestClient(application) as client:
            yield client
    finally:
        mongo = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
        try:
            mongo.drop_database(database_name)
        finally:
            mongo.close()


def _register_and_login(client: TestClient) -> dict[str, str]:
    email = f"integration-{uuid4().hex}@example.com"
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "integration-password",
            "full_name": "Integration Test",
        },
    )
    assert registration.status_code == 201, registration.text
    login = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "integration-password"},
    )
    assert login.status_code == 200, login.text
    return login.json()


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            fields[key] = value.lstrip()
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_live_mongodb_auth_refresh_and_empty_history(live_client: TestClient):
    tokens = _register_and_login(live_client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    refresh = live_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    history = live_client.get("/api/v1/history/sessions", headers=headers)

    assert refresh.status_code == 200, refresh.text
    assert history.status_code == 200, history.text
    assert history.json() == []


def test_live_rag_sse_and_persisted_citations(live_client: TestClient):
    tokens = _register_and_login(live_client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = live_client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"message": "What does CIS Safeguard 5.6 require?"},
    )

    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]
    assert "error" not in event_names, response.text
    assert event_names[0] == "started"
    assert events[0][1]["mode"] in {"fast", "complex"}
    assert event_names[1] == "metadata"
    assert "delta" in event_names
    assert event_names[-1] == "done"

    metadata = events[1][1]
    assert metadata["sources"]
    source = metadata["sources"][0]
    assert source["document_id"]
    assert source["title"]
    assert source["chunk_text"]
    assert source["score"] is not None

    assistant_text = "".join(
        payload["content"]
        for event, payload in events
        if event == "delta"
    )
    session_id = events[-1][1]["session_id"]
    assert assistant_text.strip()

    detail = live_client.get(
        f"/api/v1/history/sessions/{session_id}",
        headers=headers,
    )
    assert events[0][1]["session_id"] == session_id
    assert detail.status_code == 200, detail.text
    messages = detail.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == assistant_text
    assert messages[1]["sources"] == metadata["sources"]

    deletion = live_client.delete(
        f"/api/v1/history/sessions/{session_id}",
        headers=headers,
    )
    assert deletion.status_code == 200, deletion.text
    assert deletion.json() == {"deleted": True, "session_id": session_id}
