"""Measure cold/warm retrieval and streamed answer latency without MongoDB."""

from __future__ import annotations

import argparse
import asyncio
import time

from ollama import AsyncClient

from backend.core.config import get_settings
from backend.db.weaviate import WeaviateManager
from backend.services.fast_llm_service import FastLLMService
from backend.services.fast_rag_service import FastRAGService


async def benchmark(question: str, runs: int, cold: bool) -> None:
    settings = get_settings()
    if cold:
        client = AsyncClient(host=settings.ollama_host)
        try:
            await client.generate(model=settings.embedding_model, prompt="", keep_alive=0)
            await client.generate(model=settings.answer_model, prompt="", keep_alive=0)
        finally:
            await client.close()

    manager = WeaviateManager()
    await manager.connect(settings)
    rag = FastRAGService(settings, manager)
    llm = FastLLMService(settings)
    try:
        for run in range(1, runs + 1):
            started = time.perf_counter()
            context = await rag.retrieve(question)
            retrieved = time.perf_counter()
            first_token_at: float | None = None
            answer_parts: list[str] = []
            async for token in llm.stream_answer(
                question,
                context.chunks,
                context.is_complex,
            ):
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                answer_parts.append(token)
            finished = time.perf_counter()
            print(
                f"run={run} mode={'complex' if context.is_complex else 'fast'} "
                f"retrieval={retrieved - started:.3f}s "
                f"first_token={(first_token_at or finished) - started:.3f}s "
                f"total={finished - started:.3f}s "
                f"sources={len(context.sources)} chars={len(''.join(answer_parts))}"
            )
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "question",
        nargs="?",
        default="What does CIS Safeguard 5.6 require?",
    )
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--cold", action="store_true")
    args = parser.parse_args()
    asyncio.run(benchmark(args.question, args.runs, args.cold))


if __name__ == "__main__":
    main()
