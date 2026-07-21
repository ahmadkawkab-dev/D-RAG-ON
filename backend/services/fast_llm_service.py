"""Cancellable Ollama streaming with warm models and bounded concise answers."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from typing import AsyncIterator, Any

from ollama import AsyncClient

from backend.core.config import Settings


class FastLLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: OrderedDict[str, str] = OrderedDict()

    async def stream_answer(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        is_complex: bool = False,
    ) -> AsyncIterator[str]:
        cache_key = self._cache_key(question, chunks)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            yield cached
            return

        timeout = getattr(
            self.settings,
            "complex_answer_timeout_seconds" if is_complex else "fast_answer_timeout_seconds",
            900.0 if is_complex else 5.0,
        )
        retrieval_seconds = max(
            (float(chunk.get("_retrieval_elapsed_seconds") or 0.0) for chunk in chunks),
            default=0.0,
        )
        # Reserve a small margin for the fallback event and persistence work.
        timeout = max(0.05, timeout - retrieval_seconds - 0.1)
        max_tokens = getattr(
            self.settings,
            "complex_answer_max_tokens" if is_complex else "fast_answer_max_tokens",
            640 if is_complex else 160,
        )
        prompt = self._build_prompt(question, chunks, is_complex)
        parts: list[str] = []
        client = AsyncClient(
            host=self.settings.ollama_host,
            timeout=self.settings.llm_request_timeout_seconds,
        )
        try:
            try:
                async with asyncio.timeout(timeout):
                    stream = await client.chat(
                        model=self.settings.answer_model,
                        messages=[{"role": "user", "content": prompt}],
                        stream=True,
                        think=False,
                        keep_alive=getattr(self.settings, "answer_keep_alive", "30m"),
                        options={
                            "num_predict": max_tokens,
                            "temperature": 0.1,
                            "num_ctx": 4096,
                        },
                    )
                    async for event in stream:
                        token = event["message"]["content"]
                        if token:
                            parts.append(token)
                            yield token
            except TimeoutError:
                if not parts:
                    fallback = self._source_fallback(chunks)
                    parts.append(fallback)
                    yield fallback
        finally:
            await client.close()

        answer = "".join(parts).strip()
        if answer:
            self._remember(cache_key, answer)

    def _build_prompt(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        is_complex: bool,
    ) -> str:
        limit = getattr(self.settings, "answer_context_chars_per_chunk", 1800)
        context = "\n\n".join(
            f"[{index}] {str(chunk.get('text') or '')[:limit]}"
            for index, chunk in enumerate(chunks, start=1)
        )
        length = (
            "Give a structured but focused answer."
            if is_complex
            else "Answer directly in 2-5 concise sentences."
        )
        return (
            "Use ONLY the numbered context. "
            f"{length} Cite only the strongest supporting source inline as "
            "[1], [2], etc.; do not add a separate sources list. If the context "
            "cannot answer the question, reply exactly: Question irrelevant to "
            "the available document context.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
        )

    @staticmethod
    def _source_fallback(chunks: list[dict[str, Any]]) -> str:
        if not chunks:
            return "Question irrelevant to the available document context."
        text = " ".join(str(chunks[0].get("text") or "").split())
        if len(text) > 420:
            text = f"{text[:417].rstrip()}..."
        return f"{text} [1]"

    @staticmethod
    def _cache_key(question: str, chunks: list[dict[str, Any]]) -> str:
        evidence = "\n".join(str(chunk.get("text") or "") for chunk in chunks)
        return hashlib.sha256(f"{question.strip().lower()}\n{evidence}".encode()).hexdigest()

    def _remember(self, key: str, answer: str) -> None:
        cache_size = getattr(self.settings, "answer_cache_size", 128)
        if cache_size == 0:
            return
        self._cache[key] = answer
        self._cache.move_to_end(key)
        while len(self._cache) > cache_size:
            self._cache.popitem(last=False)
