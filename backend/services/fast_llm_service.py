"""Cancellable Ollama streaming with warm KV state and answer reuse."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import AsyncIterator, Any

from ollama import AsyncClient

from backend.core.config import Settings
from backend.services.cache import CacheInfo, TTLCache


logger = logging.getLogger(__name__)
PROMPT_VERSION = "grounded-rag-v4-complete-streaming"
MAX_CONTINUATIONS = 1
RAG_SYSTEM_PROMPT = (
    "You are a grounded document assistant. Use ONLY the numbered context "
    "provided by the user. Cite only the strongest supporting sources inline "
    "as [1], [2], and so on; never add a separate source list. If the context "
    "cannot answer the question, reply exactly: Question irrelevant to the "
    "available document context."
)


class FastLLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._answer_cache: TTLCache[str, str] = TTLCache(
            settings.answer_cache_size,
            settings.answer_cache_ttl_seconds,
        )

    async def warm(self) -> None:
        """Best-effort preload so the first request can reuse model state."""
        client = AsyncClient(
            host=self.settings.ollama_host,
            timeout=self.settings.llm_request_timeout_seconds,
        )
        try:
            await client.generate(
                model=self.settings.answer_model,
                prompt="",
                stream=False,
                keep_alive=self.settings.answer_keep_alive,
            )
        except Exception:
            logger.warning("Unable to preload the answer model", exc_info=True)
        finally:
            await client.close()

    async def stream_answer(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        is_complex: bool = False,
    ) -> AsyncIterator[str]:
        cache_key = self._cache_key(question, chunks, is_complex)
        cached = self._answer_cache.get(cache_key)
        if cached is not None:
            async for chunk in self._replay_cached(cached):
                yield chunk
            return

        timeout = (
            self.settings.complex_answer_timeout_seconds
            if is_complex
            else self.settings.fast_answer_timeout_seconds
        )
        retrieval_seconds = max(
            (
                float(chunk.get("_retrieval_elapsed_seconds") or 0.0)
                for chunk in chunks
            ),
            default=0.0,
        )
        # Reserve a small margin for persistence while prioritizing completeness.
        timeout = max(0.5, timeout - retrieval_seconds - 0.1)
        max_tokens = (
            self.settings.complex_answer_max_tokens
            if is_complex
            else self.settings.fast_answer_max_tokens
        )
        prompt = self._build_prompt(question, chunks, is_complex)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        parts: list[str] = []
        completed = False
        continuations = 0
        client = AsyncClient(
            host=self.settings.ollama_host,
            timeout=self.settings.llm_request_timeout_seconds,
        )
        try:
            try:
                async with asyncio.timeout(timeout):
                    while True:
                        done_reason: str | None = None
                        stream = await client.chat(
                            model=self.settings.answer_model,
                            messages=messages,
                            stream=True,
                            think=False,
                            keep_alive=self.settings.answer_keep_alive,
                            options={
                                "num_predict": max_tokens,
                                "temperature": 0.1,
                                "num_ctx": self.settings.answer_num_ctx,
                            },
                        )
                        async for event in stream:
                            token = event["message"]["content"]
                            if token:
                                parts.append(token)
                                yield token
                            done_reason = self._done_reason(event) or done_reason

                        if done_reason != "length":
                            completed = True
                            break
                        if continuations >= MAX_CONTINUATIONS:
                            break

                        messages.extend(
                            [
                                {
                                    "role": "assistant",
                                    "content": "".join(parts),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        "Continue exactly where the answer stopped. "
                                        "Output only the continuation, finish the "
                                        "explanation, and retain inline citations."
                                    ),
                                },
                            ]
                        )
                        continuations += 1
            except TimeoutError as exc:
                raise RuntimeError(
                    "Answer generation timed out before completion"
                ) from exc
        finally:
            await client.close()

        if not completed:
            raise RuntimeError("Answer generation reached its completion limit")

        answer = "".join(parts).strip()
        if answer:
            self._answer_cache.put(cache_key, answer)

    @property
    def answer_cache_info(self) -> CacheInfo:
        return self._answer_cache.info()

    def clear_answer_cache(self) -> None:
        self._answer_cache.clear()

    def _build_prompt(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        is_complex: bool,
    ) -> str:
        limit = self.settings.answer_context_chars_per_chunk
        context = "\n\n".join(
            f"[{index}] {str(chunk.get('text') or '')[:limit]}"
            for index, chunk in enumerate(chunks, start=1)
        )
        answer_style = (
            "Give a structured but focused answer."
            if is_complex
            else (
                "Give a complete explanation in 1-3 short paragraphs. "
                "Finish every sentence and do not end mid-thought."
            )
        )
        return (
            f"{answer_style}\n\nContext:\n{context}\n\n"
            f"Question: {question}\nAnswer:"
        )

    @staticmethod
    async def _replay_cached(answer: str) -> AsyncIterator[str]:
        """Replay cached text as incremental SSE-friendly chunks."""
        chunk_size = 48
        for start in range(0, len(answer), chunk_size):
            yield answer[start : start + chunk_size]
            await asyncio.sleep(0)

    @staticmethod
    def _done_reason(event: Any) -> str | None:
        if isinstance(event, dict):
            value = event.get("done_reason")
        else:
            value = getattr(event, "done_reason", None)
        return str(value) if value else None

    def _cache_key(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        is_complex: bool,
    ) -> str:
        payload = {
            "prompt_version": PROMPT_VERSION,
            "model": self.settings.answer_model,
            "num_ctx": self.settings.answer_num_ctx,
            "context_chars": self.settings.answer_context_chars_per_chunk,
            "is_complex": is_complex,
            "question": question.strip(),
            "evidence": [str(chunk.get("text") or "") for chunk in chunks],
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()
