"""Opt-in regression for answers that previously fell back to cut-off chunks."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tests.backend.test_live_integration import (
    _parse_sse,
    _register_and_login,
    live_client,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG_TESTS") != "1",
    reason="set RUN_LIVE_RAG_TESTS=1 to use local services and models",
)


def test_penetration_testing_answer_is_complete(live_client: TestClient) -> None:
    tokens = _register_and_login(live_client)
    response = live_client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"message": "Explain the concept of penetration testing."},
    )

    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert all(name != "error" for name, _ in events), response.text
    deltas = [
        payload["content"]
        for name, payload in events
        if name == "delta"
    ]
    answer = "".join(deltas).strip()

    assert len(deltas) > 5
    assert len(answer) >= 500
    assert "penetration testing" in answer.lower()
    assert "vulnerabilit" in answer.lower()
    assert not answer.endswith("... [1]")
    assert answer[-1] in ".!?])"
