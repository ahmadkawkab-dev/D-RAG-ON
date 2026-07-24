"""Shared helpers for opt-in tests against local RAG services."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG_TESTS") != "1",
    reason="set RUN_LIVE_RAG_TESTS=1 to use local services and models",
)


@pytest.fixture
def live_client() -> Iterator[TestClient]:
    settings = Settings()
    assert settings.internal_api_key is not None, (
        "RAG_INTERNAL_API_KEY is required for live integration tests"
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _internal_headers(client: TestClient) -> dict[str, str]:
    secret = client.app.state.settings.internal_api_key
    assert secret is not None
    return {
        "X-RAG-API-Key": secret.get_secret_value(),
        "X-Application-User-Id": "live-integration-user",
    }


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    event_name = "message"
    data_lines: list[str] = []

    for line in [*body.splitlines(), ""]:
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
        elif not line and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []

    return events
