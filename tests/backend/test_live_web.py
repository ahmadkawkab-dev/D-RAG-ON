"""Opt-in verification of Ollama web search using the configured API key."""

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
async def test_live_ollama_web_search_returns_structured_sources() -> None:
    settings = Settings()
    assert settings.ollama_api_key, "RAG_OLLAMA_API_KEY is not configured"
    service = GeneralChatService(settings)
    client = service._client(web=True)
    try:
        result = await service._run_tool(
            client,
            "web_search",
            {"query": "official Ollama documentation web search API"},
        )
    finally:
        await client.close()

    assert result["content"]
    assert result["sources"]
    assert all(source["source_url"].startswith("http") for source in result["sources"])
    assert all(source["metadata"]["provider"] == "ollama_web" for source in result["sources"])
