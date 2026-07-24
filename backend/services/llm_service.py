"""Bridge the synchronous local Ollama stream into an async token generator."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import AsyncIterator, Any

from ollama import Client

from agent import synthesize_answer
from backend.core.config import Settings
from main import unload_ollama_model


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream_answer(
        self,
        question: str,
        chunks: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        def publish(kind: str, value: object) -> None:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

        def produce() -> None:
            try:
                with Client(
                    host=self.settings.ollama_host,
                    timeout=self.settings.llm_request_timeout_seconds,
                ) as client:
                    synthesize_answer(
                        client,
                        self.settings.answer_model,
                        question,
                        chunks,
                        on_token=lambda token: publish("token", token),
                    )
            except Exception as exc:
                publish("error", exc)
            finally:
                unload_ollama_model(
                    self.settings.ollama_host,
                    self.settings.answer_model,
                )
                publish("done", None)

        producer = asyncio.create_task(asyncio.to_thread(produce))
        try:
            while True:
                kind, value = await queue.get()
                if kind == "token":
                    yield str(value)
                elif kind == "error":
                    raise RuntimeError("Local answer generation failed") from value
                else:
                    break
            await producer
        finally:
            if not producer.done():
                # A cancelled asyncio wrapper cannot stop its worker thread.
                # Wait for bounded model cleanup before releasing the model lock.
                await asyncio.shield(producer)
