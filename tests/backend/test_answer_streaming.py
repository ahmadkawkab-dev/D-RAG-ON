from __future__ import annotations

import pytest

from backend.core.config import Settings
from backend.services.fast_llm_service import FastLLMService


@pytest.mark.asyncio
async def test_cached_answer_is_replayed_as_incremental_chunks() -> None:
    settings = Settings(_env_file=None, connect_external_services_on_startup=False)
    service = FastLLMService(settings)
    question = "Explain penetration testing"
    chunks = [{"text": "Grounded evidence"}]
    answer = "A complete cached explanation. " * 20
    cache_key = service._cache_key(question, chunks, False)
    service._answer_cache.put(cache_key, answer)

    streamed = [part async for part in service.stream_answer(question, chunks)]

    assert len(streamed) > 1
    assert "".join(streamed) == answer
