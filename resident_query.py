"""Resident interactive query engine for low-latency Streamlit chat."""

from __future__ import annotations

import gc
import threading
import time
from typing import Any

import weaviate
from ollama import Client

from agent import retrieve, synthesize_answer
from ingestion.embedder import Embedder
from reranker import Reranker
from response_cache import DEFAULT_RESPONSE_CACHE_PATH, ResponseCache
from rerank_policy import (
    DEFAULT_HEAVY_RERANKER,
    DEFAULT_LIGHT_RERANKER,
    choose_rerank_route,
    deduplicate_candidates,
    exact_clause_matches,
)


class ResidentQueryEngine:
    """Keep lightweight query models alive across interactive questions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._embedder: Embedder | None = None
        self._response_cache = ResponseCache(
            DEFAULT_RESPONSE_CACHE_PATH
        )
        self._embedder_key: tuple[str, str] | None = None
        self._light_reranker: Reranker | None = None
        self._reranker_key: tuple[str, str | None] | None = None

    def _get_embedder(self, model: str, host: str) -> Embedder:
        key = (model, host)
        if self._embedder is None or self._embedder_key != key:
            if self._embedder is not None:
                self._embedder.close()
            self._embedder = Embedder(model_name=model, host=host)
            self._embedder_key = key
        return self._embedder

    def _get_light_reranker(self, model: str, device: str | None) -> Reranker:
        key = (model, device)
        if self._light_reranker is None or self._reranker_key != key:
            self._drop_light_reranker()
            self._light_reranker = Reranker(model_name=model, device=device)
            self._reranker_key = key
        return self._light_reranker

    def _drop_light_reranker(self) -> None:
        if self._light_reranker is None:
            return
        self._light_reranker = None
        self._reranker_key = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:
            pass

    def query(
        self,
        query: str,
        configuration: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one serialized query while publishing logs and streamed text."""

        with self._lock:
            started = time.monotonic()
            logs: list[str] = state["logs"]

            cached = self._response_cache.get(query, configuration)
            if cached is not None:
                route = dict(cached.get("rerank_route") or {})
                route.update({
                    "route": "cache",
                    "cache_hit": True,
                    "reason": "identical normalized question and settings",
                })
                cached["query"] = query
                cached["rerank_route"] = route
                logs.append("[phase 1/1] response cache hit")
                state["answer"] = cached.get("answer") or ""
                state["elapsed_seconds"] = time.monotonic() - started
                state["result"] = cached
                state["done"] = True
                return cached

            def emit(line: str) -> None:
                logs.append(line)

            collection_name = configuration.get("collection", "DocumentChunks")
            embed_model = configuration.get("embed_model", "embeddinggemma")
            host = configuration.get("host", "http://localhost:11434")
            light_model = configuration.get("rerank_model", DEFAULT_LIGHT_RERANKER)
            heavy_model = configuration.get("heavy_rerank_model", DEFAULT_HEAVY_RERANKER)
            device = configuration.get("rerank_device")
            retrieve_k = int(configuration.get("retrieve_k", 20))
            top_n = int(configuration.get("top_n", 5))
            alpha = float(configuration.get("alpha", 0.5))
            relevance_threshold = float(configuration.get("relevance_threshold", 0.20))

            emit(f"[phase 1/3] embed and check semantic response cache")
            embedder = self._get_embedder(embed_model, host)
            query_vector = embedder.embed_query(query)
            semantic = self._response_cache.semantic_get(
                query,
                configuration,
                query_vector,
                minimum_similarity=float(
                    configuration.get("semantic_cache_threshold", 0.88)
                ),
            )
            if semantic is not None:
                cached, similarity, cached_question = semantic
                route = dict(cached.get("rerank_route") or {})
                route.update({
                    "route": "semantic_cache",
                    "cache_hit": True,
                    "semantic_similarity": similarity,
                    "matched_question": cached_question,
                    "reason": "high-confidence semantic match with a cached request",
                })
                cached["query"] = query
                cached["rerank_route"] = route
                logs.append(
                    f"semantic response cache hit (similarity={similarity:.3f})"
                )
                state["answer"] = cached.get("answer") or ""
                state["elapsed_seconds"] = time.monotonic() - started
                state["result"] = cached
                state["done"] = True
                return cached

            related_context = self._response_cache.semantic_get(
                query,
                configuration,
                query_vector,
                minimum_similarity=float(
                    configuration.get("related_cache_threshold", 0.72)
                ),
                unanchored_minimum=0.72,
            )
            related_match_kind = "semantic"
            if related_context is None:
                related_context = self._response_cache.topic_get(
                    query,
                    configuration,
                    minimum_overlap=float(
                        configuration.get("related_topic_overlap", 0.50)
                    ),
                )
                related_match_kind = "lexical_topic"

            emit(f"[phase 1/3] retrieve with warm {embed_model}")
            client = weaviate.connect_to_local()
            try:
                collection = client.collections.get(collection_name)
                candidates = retrieve(
                    collection,
                    embedder,
                    query,
                    retrieve_k,
                    alpha,
                    query_vector=query_vector,
                )
            finally:
                client.close()
            emit(f"retrieved {len(candidates)} candidates")

            exact = exact_clause_matches(query, candidates)
            if exact:
                ranked = [
                    {**candidate, "rerank_score": 1.0}
                    for candidate in exact[:top_n]
                ]
                route = {
                    "route": "exact",
                    "reason": "high-confidence retrieval matched the named clause",
                    "selected_model": None,
                    "escalated": False,
                    "rerank_bypassed": True,
                }
                emit("[phase 2/3] exact clause match; reranker bypassed")
            else:
                unique = deduplicate_candidates(candidates)
                light_k = min(
                    len(unique),
                    max(top_n, int(configuration.get("light_rerank_k", 8))),
                )
                emit(f"[phase 2/3] warm lightweight rerank with {light_model}")
                reranker = self._get_light_reranker(light_model, device)
                light_ranked = reranker.rerank(
                    query, unique[:light_k], top_n=max(top_n, 2)
                )
                route = choose_rerank_route(
                    query,
                    light_ranked,
                    relevance_floor=relevance_threshold,
                    confidence_threshold=float(
                        configuration.get("rerank_confidence_threshold", 0.80)
                    ),
                    margin_threshold=float(
                        configuration.get("rerank_margin_threshold", 0.10)
                    ),
                )
                route.update({
                    "selected_model": light_model,
                    "escalated": False,
                    "rerank_bypassed": False,
                })
                if related_context is not None and route["route"] == "heavy":
                    _, similarity, matched_question = related_context
                    route.update({
                        "route": "related_cache",
                        "reason": "related cached topic keeps the request on the fast reranker",
                        "related_similarity": similarity,
                        "matched_question": matched_question,
                        "cache_hit": False,
                        "related_match_kind": related_match_kind,
                    })
                    emit(
                        f"related topic cache assist (similarity={similarity:.3f}); "
                        "4B escalation skipped"
                    )

                if (
                    configuration.get("adaptive_rerank", True)
                    and route["route"] == "heavy"
                    and heavy_model != light_model
                ):
                    emit(f"rerank escalation: {route['reason']}")
                    del reranker
                    self._drop_light_reranker()
                    heavy_k = min(
                        len(unique),
                        max(top_n, int(configuration.get("heavy_rerank_k", 12))),
                    )
                    heavy = Reranker(model_name=heavy_model, device=device)
                    try:
                        ranked = heavy.rerank(
                            query, unique[:heavy_k], top_n=top_n
                        )
                    finally:
                        del heavy
                        gc.collect()
                    route.update({
                        "selected_model": heavy_model,
                        "escalated": True,
                    })
                else:
                    ranked = light_ranked[:top_n]
                    emit(f"rerank route: {route['route']} ({route['reason']})")

            top_score = float(ranked[0].get("rerank_score", 0.0)) if ranked else 0.0
            is_relevant = bool(ranked) and top_score >= relevance_threshold
            answer_text = None
            if configuration.get("answer", False):
                if not is_relevant:
                    answer_text = "Question irrelevant to the available document context."
                    state["answer"] = answer_text
                else:
                    emit(f"[phase 3/3] stream answer with {configuration.get('answer_model', 'qwen2.5:1.5b')}")
                    state["phase"] = "answer"

                    def on_token(token: str) -> None:
                        state["answer"] += token

                    with Client(host=host, timeout=None) as chat_client:
                        answer_text = synthesize_answer(
                            chat_client,
                            configuration.get("answer_model", "qwen2.5:1.5b"),
                            query,
                            ranked,
                            on_token=on_token,
                        )
            else:
                emit("[phase 3/3] answer synthesis skipped")

            result = {
                "query": query,
                "ranked": ranked,
                "answer": answer_text,
                "is_relevant": is_relevant,
                "top_relevance_score": top_score,
                "relevance_threshold": relevance_threshold,
                "rerank_route": route,
            }
            result["rerank_route"]["cache_hit"] = False
            self._response_cache.put(query, configuration, result, query_vector)
            state["elapsed_seconds"] = time.monotonic() - started
            state["result"] = result
            state["done"] = True
            return result


_ENGINE = ResidentQueryEngine()


def run_resident_query(
    query: str,
    configuration: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    return _ENGINE.query(query, configuration, state)

