"""RAG retrieval orchestration and citation normalization."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Any

from backend.core.config import Settings
from backend.db.weaviate import WeaviateManager
from backend.schemas.chat import Citation
from main import run_query_pipeline


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedContext:
    chunks: list[dict[str, Any]]
    sources: list[Citation]
    is_relevant: bool
    is_complex: bool = False


class RAGService:
    """Use the existing local pipeline behind an async, serialized boundary."""

    def __init__(
        self,
        settings: Settings,
        weaviate_manager: WeaviateManager,
    ) -> None:
        self.settings = settings
        self.weaviate_manager = weaviate_manager
        self._model_lock = asyncio.Lock()

    @asynccontextmanager
    async def model_execution(self) -> AsyncIterator[None]:
        """Keep retrieval, reranking, and generation sequential across requests."""
        async with self._model_lock:
            yield

    async def retrieve(self, message: str) -> RetrievedContext:
        query = self.prepare_query(message)
        result = await asyncio.to_thread(
            run_query_pipeline,
            query,
            collection=self.settings.weaviate_collection,
            embed_model=self.settings.embedding_model,
            host=self.settings.ollama_host,
            rerank_model=self.settings.light_reranker_model,
            heavy_rerank_model=self.settings.heavy_reranker_model,
            rerank_device=self.settings.rerank_device,
            retrieve_k=self.settings.retrieve_k,
            alpha=self.settings.hybrid_alpha,
            top_n=self.settings.top_n,
            answer=False,
            relevance_threshold=self.settings.relevance_threshold,
            on_line=logger.info,
            weaviate_client=self.weaviate_manager.client,
        )
        chunks = list(result.get("ranked") or [])
        return RetrievedContext(
            chunks=chunks,
            sources=[self.citation_from_chunk(chunk) for chunk in chunks],
            is_relevant=bool(result.get("is_relevant")),
        )

    @staticmethod
    def prepare_query(message: str) -> str:
        """Normalize the query; this is the extension point for future expansion."""
        return " ".join(message.split())

    @staticmethod
    def citation_from_chunk(chunk: dict[str, Any]) -> Citation:
        metadata = chunk.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

        source_file = metadata.get("source_file")
        document_id = (
            metadata.get("document_id")
            or metadata.get("doc_id")
            or source_file
            or metadata.get("chunk_id")
            or "unknown"
        )
        title = (
            metadata.get("title")
            or metadata.get("doc_title")
            or source_file
            or "Untitled document"
        )
        raw_breadcrumb = metadata.get("breadcrumb")
        if isinstance(raw_breadcrumb, (list, tuple)):
            breadcrumb_items = [str(item) for item in raw_breadcrumb if item]
        elif raw_breadcrumb:
            breadcrumb_items = [str(raw_breadcrumb)]
        else:
            breadcrumb_items = []
        breadcrumb_text = " / ".join(breadcrumb_items)
        section = (
            metadata.get("section")
            or metadata.get("clause_number")
            or breadcrumb_text
        )
        page = metadata.get("page_number") or metadata.get("page_start")
        try:
            page_number = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_number = None
        rerank_score = _optional_float(chunk.get("rerank_score"))
        hybrid_score = _optional_float(chunk.get("score"))
        chunk_text = str(chunk.get("text") or "")
        chunk_id = metadata.get("chunk_id") or chunk.get("id")
        summary = " ".join(chunk_text.split())
        summary = summary if len(summary) <= 280 else f"{summary[:277].rstrip()}..."
        return Citation(
            document_id=str(document_id),
            title=str(title),
            source_url=metadata.get("source_url"),
            file_path=metadata.get("file_path") or source_file,
            chunk_text=chunk_text,
            chunk_id=str(chunk_id) if chunk_id else None,
            breadcrumb=breadcrumb_items,
            summary=summary,
            metadata=metadata,
            score=rerank_score if rerank_score is not None else hybrid_score,
            relevance=rerank_score,
            page_number=page_number,
            section=str(section) if section else None,
        )


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
