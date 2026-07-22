"""Opt-in General Chat agent-to-web integration verification."""

from __future__ import annotations

import os

import pytest

from backend.core.config import Settings
from backend.services.general_chat_service import GeneralChatService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_WEB_TESTS") != "1",
    reason="set RUN_LIVE_WEB_TESTS=1 to call Ollama web search",
)


@pytest.mark.asyncio
async def test_general_chat_agent_selects_web_search() -> None:
    settings = Settings()
    assert settings.ollama_api_key, "RAG_OLLAMA_API_KEY is not configured"
    service = GeneralChatService(settings)

    prepared = await service.prepare(
        "Search the web for the current official Ollama API documentation.",
        [],
    )

    assert prepared.web_enabled is True
    assert prepared.sources
    assert any(message.get("role") == "tool" for message in prepared.messages)
