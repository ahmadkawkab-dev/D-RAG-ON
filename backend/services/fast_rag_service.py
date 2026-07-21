"""Low-latency retrieval path with precision reranking only for complex queries."""

from __future__ import annotations

import asyncio
from typing import Any
import time

from agent import retrieve
from ingestion.embedder import Embedder
from main import run_adaptive_rerank, unload_ollama_model
from rerank_policy import deduplicate_candidates, exact_clause_matches

from backend.services.rag_service import RAGService, RetrievedContext


class FastRAGService(RAGService):
    async def retrieve(self, message: str) -> RetrievedContext:
        query = self.prepare_query(message)
        is_complex = self.is_complex_query(query)
        started = time.perf_counter()
        chunks = await asyncio.to_thread(self._retrieve_sync, query, is_complex)
        threshold = self.settings.relevance_threshold
        top_score = float(chunks[0].get("rerank_score") or 0.0) if chunks else 0.0
        retrieval_seconds = time.perf_counter() - started
        for chunk in chunks:
            chunk["_retrieval_elapsed_seconds"] = retrieval_seconds
        return RetrievedContext(
            chunks=chunks,
            sources=[self.citation_from_chunk(chunk) for chunk in chunks],
            is_relevant=bool(chunks) and top_score >= threshold,
            is_complex=is_complex,
        )

    def is_complex_query(self, message: str) -> bool:
        normalized = message.lower()
        word_limit = getattr(self.settings, "fast_query_max_words", 24)
        markers = (
            "compare", "contrast", "analyze", "evaluate", "synthesize",
            "comprehensive", "in detail", "step by step", "across all",
            "advantages and disadvantages", "pros and cons", "report",
        )
        return (
            len(normalized.split()) > word_limit
            or normalized.count("?") > 1
            or any(marker in normalized for marker in markers)
        )

    def _retrieve_sync(self, query: str, is_complex: bool) -> list[dict[str, Any]]:
        retrieve_k = (
            self.settings.retrieve_k
            if is_complex
            else getattr(self.settings, "fast_retrieve_k", 8)
        )
        top_n = (
            self.settings.top_n
            if is_complex
            else getattr(self.settings, "fast_top_n", 3)
        )
        embedder = Embedder(
            model_name=self.settings.embedding_model,
            host=self.settings.ollama_host,
        )
        try:
            collection = self.weaviate_manager.client.collections.get(
                self.settings.weaviate_collection
            )
            candidates = retrieve(
                collection,
                embedder,
                query,
                retrieve_k,
                self.settings.hybrid_alpha,
            )
        finally:
            embedder.close()

        exact = exact_clause_matches(query, candidates)
        if exact:
            return [
                {**candidate, "rerank_score": 1.0}
                for candidate in exact[:top_n]
            ]

        unique = deduplicate_candidates(candidates)
        if not is_complex:
            return [
                {
                    **candidate,
                    "rerank_score": float(candidate.get("score") or 0.0),
                }
                for candidate in unique[:top_n]
            ]
        # The precision rerankers can consume most of an 8 GB GPU. Complex
        # requests may take longer, so free the warm Ollama models first.
        unload_ollama_model(self.settings.ollama_host, self.settings.embedding_model)
        unload_ollama_model(self.settings.ollama_host, self.settings.answer_model)


        ranked, _route = run_adaptive_rerank(
            query,
            unique,
            light_model=self.settings.light_reranker_model,
            heavy_model=self.settings.heavy_reranker_model,
            device=self.settings.rerank_device,
            top_n=top_n,
            adaptive=True,
            relevance_floor=self.settings.relevance_threshold,
        )
        return ranked
