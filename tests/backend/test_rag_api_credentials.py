from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.schemas.chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionResponse,
)


FORBIDDEN_CREDENTIAL_FIELDS = {
    "api_key",
    "authorization",
    "bearer_token",
    "credential",
    "model_access_token",
    "token",
}


def test_chat_request_does_not_accept_rag_api_credentials() -> None:
    assert FORBIDDEN_CREDENTIAL_FIELDS.isdisjoint(ChatRequest.model_fields)

    with pytest.raises(ValidationError):
        ChatRequest(message="hello", api_key="browser-supplied-value")


@pytest.mark.parametrize(
    "response_model",
    [ChatResponse, ChatSessionResponse, ChatMessageResponse],
)
def test_public_chat_responses_do_not_expose_credentials(response_model: type) -> None:
    assert FORBIDDEN_CREDENTIAL_FIELDS.isdisjoint(response_model.model_fields)


def test_frontend_client_has_no_rag_api_credential_configuration() -> None:
    client_source = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "client.ts"
    ).read_text(encoding="utf-8")

    assert "VITE_RAG_API_KEY" not in client_source
    assert "VITE_RAG_BEARER_TOKEN" not in client_source
    assert '"api_key"' not in client_source
