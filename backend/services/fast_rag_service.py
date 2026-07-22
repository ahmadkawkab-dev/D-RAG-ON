"""Low-latency retrieval with bounded reuse and precision reranking."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
from typing import Any

from agent import retrieve
from ingestion.embedder import Embedder
from main import run_adaptive_rerank, unload_ollama_model
from rerank_policy import deduplicate_candidates, exact_clause_matches

from backend.core.config import Settings
from backend.db.weaviate import WeaviateManager
from backend.services.cache import CacheInfo, TTLCache
from backend.services.rag_service import RAGService, RetrievedContext


class FastRAGService(RAGService):
    def __init__(
        self,
        settings: Settings,
        weaviate_manager: WeaviateManager,
    ) -> None:
        super().__init__(settings, weaviate_manager)
        self._retrieval_cache: TTLCache[str, RetrievedContext] = TTLCache(
            settings.retrieval_cache_size,
            settings.retrieval_cache_ttl_seconds,
        )

    async def retrieve(self, message: str) -> RetrievedContext:
        query = self.prepare_query(message)
        is_complex = self.is_complex_query(query)
        cache_key = self._retrieval_cache_key(query, is_complex)
        cached = self._retrieval_cache.get(cache_key)
        if cached is not None:
            return self._copy_context(cached, retrieval_seconds=0.0)

        started = time.perf_counter()
        chunks = await asyncio.to_thread(self._retrieve_sync, query, is_complex)
        threshold = self.settings.relevance_threshold
        top_score = float(chunks[0].get("rerank_score") or 0.0) if chunks else 0.0
        retrieval_seconds = time.perf_counter() - started
        for chunk in chunks:
            chunk["_retrieval_elapsed_seconds"] = retrieval_seconds
        context = RetrievedContext(
            chunks=chunks,
            sources=[self.citation_from_chunk(chunk) for chunk in chunks],
            is_relevant=bool(chunks) and top_score >= threshold,
            is_complex=is_complex,
        )
        self._retrieval_cache.put(cache_key, copy.deepcopy(context))
        return context

    @property
    def retrieval_cache_info(self) -> CacheInfo:
        return self._retrieval_cache.info()

    def clear_retrieval_cache(self) -> None:
        self._retrieval_cache.clear()

    def _retrieval_cache_key(self, query: str, is_complex: bool) -> str:
        profile = {
            "revision": self.settings.retrieval_cache_revision,
            "query": query,
            "complex": is_complex,
            "collection": self.settings.weaviate_collection,
            "embedding_model": self.settings.embedding_model,
            "light_reranker_model": self.settings.light_reranker_model,
            "heavy_reranker_model": self.settings.heavy_reranker_model,
            "retrieve_k": (
                self.settings.retrieve_k
                if is_complex
                else self.settings.fast_retrieve_k
            ),
            "top_n": (
                self.settings.top_n
                if is_complex
                else self.settings.fast_top_n
            ),
            "hybrid_alpha": self.settings.hybrid_alpha,
            "relevance_threshold": self.settings.relevance_threshold,
        }
        payload = json.dumps(profile, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _copy_context(
        context: RetrievedContext,
        *,
        retrieval_seconds: float,
    ) -> RetrievedContext:
        copied = copy.deepcopy(context)
        for chunk in copied.chunks:
            chunk["_retrieval_elapsed_seconds"] = retrieval_seconds
        return copied

    def is_complex_query(self, message: str) -> bool:
        normalized = message.lower()
        word_limit = self.settings.fast_query_max_words
        markers = (
            "compare",
            "contrast",
            "analyze",
            "evaluate",
            "synthesize",
            "comprehensive",
            "in detail",
            "step by step",
            "across all",
            "advantages and disadvantages",
            "pros and cons",
            "report",
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
            else self.settings.fast_retrieve_k
        )
        top_n = self.settings.top_n if is_complex else self.settings.fast_top_n
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

        # Precision rerankers can consume most of an 8 GB GPU. Complex requests
        # release warm Ollama models first; ordinary requests retain their KV cache.
        unload_ollama_model(self.settings.ollama_host, self.settings.embedding_model)
        unload_ollama_model(self.settings.ollama_host, self.settings.answer_model)
        unload_ollama_model(self.settings.ollama_host, self.settings.general_chat_model)

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
