from __future__ import annotations

from typing import Any

import pytest

from backend.core.config import Settings
from backend.services.cache import TTLCache
from backend.services.fast_llm_service import FastLLMService
from backend.services.fast_rag_service import FastRAGService
from backend.services.general_chat_service import GeneralChatService


def test_ttl_cache_expires_and_evicts_least_recently_used() -> None:
    now = [0.0]
    cache: TTLCache[str, str] = TTLCache(
        max_size=2,
        ttl_seconds=10.0,
        clock=lambda: now[0],
    )

    cache.put("a", "one")
    cache.put("b", "two")
    assert cache.get("a") == "one"
    cache.put("c", "three")

    assert cache.get("b") is None
    now[0] = 11.0
    assert cache.get("a") is None
    assert cache.info().size == 1


@pytest.mark.asyncio
async def test_document_retrieval_cache_reuses_an_isolated_copy() -> None:
    settings = Settings(
        _env_file=None,
        connect_external_services_on_startup=False,
        retrieval_cache_size=4,
        retrieval_cache_ttl_seconds=60,
    )
    service = FastRAGService(settings, object())  # type: ignore[arg-type]
    calls = 0

    def fake_retrieve(query: str, is_complex: bool) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        assert query == "Explain control 5"
        assert is_complex is False
        return [
            {
                "text": "Control 5 requires account management.",
                "score": 0.88,
                "rerank_score": 0.88,
                "metadata": {"document_id": "doc-1", "title": "Controls"},
            }
        ]

    service._retrieve_sync = fake_retrieve  # type: ignore[method-assign]
    first = await service.retrieve("  Explain   control 5  ")
    first.chunks[0]["text"] = "mutated caller copy"
    second = await service.retrieve("Explain control 5")

    assert calls == 1
    assert second.chunks[0]["text"] == "Control 5 requires account management."
    assert second.chunks[0]["_retrieval_elapsed_seconds"] == 0.0
    assert service.retrieval_cache_info.hits == 1


def test_answer_cache_key_tracks_prompt_model_and_evidence() -> None:
    settings = Settings(_env_file=None, connect_external_services_on_startup=False)
    service = FastLLMService(settings)
    chunks = [{"text": "Evidence one"}]

    base = service._cache_key("Question", chunks, False)
    assert base != service._cache_key("Question", chunks, True)
    assert base != service._cache_key("Question", [{"text": "Evidence two"}], False)


class _WebItem:
    def model_dump(self) -> dict[str, str]:
        return {
            "title": "Result title",
            "url": "https://example.test/result",
            "content": "Current result content",
        }


class _WebResponse:
    results = [_WebItem()]


class _WebClient:
    def __init__(self) -> None:
        self.calls = 0

    async def web_search(self, query: str, max_results: int) -> _WebResponse:
        self.calls += 1
        assert query == "current result"
        assert max_results == 5
        return _WebResponse()


@pytest.mark.asyncio
async def test_web_retrieval_cache_is_bounded_and_copy_safe() -> None:
    settings = Settings(
        _env_file=None,
        connect_external_services_on_startup=False,
        ollama_api_key="test-key",
        general_web_cache_size=4,
        general_web_cache_ttl_seconds=60,
    )
    service = GeneralChatService(settings)
    client = _WebClient()

    first = await service._run_tool(
        client,  # type: ignore[arg-type]
        "web_search",
        {"query": "current result"},
    )
    first["sources"][0]["title"] = "mutated caller copy"
    second = await service._run_tool(
        client,  # type: ignore[arg-type]
        "web_search",
        {"query": "current result"},
    )

    assert client.calls == 1
    assert second["sources"][0]["title"] == "Result title"
    assert service.web_cache_info.hits == 1
