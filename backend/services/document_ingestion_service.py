"""Reuse the established PDF parse/embed/store pipeline for internal uploads."""

from __future__ import annotations

from pathlib import Path

from ingestion.embedder import Embedder
from ingestion.store import get_or_create_collection, upload_chunks
from parse import PDFChunkingPipeline, PipelineConfig

from backend.core.config import Settings
from backend.db.weaviate import WeaviateManager
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService


class DocumentIngestionService:
    def __init__(
        self,
        settings: Settings,
        weaviate: WeaviateManager,
        rag_service: RAGService,
        llm_service: LLMService,
    ) -> None:
        self._settings = settings
        self._weaviate = weaviate
        self._rag_service = rag_service
        self._llm_service = llm_service

    def ingest_pdf(self, pdf_path: Path, document_id: str) -> dict[str, object]:
        pipeline = PDFChunkingPipeline(PipelineConfig())
        chunks = pipeline.run(pdf_path)
        if not chunks:
            raise ValueError("The PDF did not produce any indexable content")

        texts = [chunk.text for chunk in chunks]
        metadata = [chunk.metadata.to_json() for chunk in chunks]
        stable_ids = [
            f"{document_id}-{chunk.metadata.chunk_index:05d}"
            for chunk in chunks
        ]
        embedder = Embedder(
            model_name=self._settings.embedding_model,
            host=self._settings.ollama_host,
        )
        try:
            vectors = embedder.embed_passages(texts, batch_size=32)
        finally:
            embedder.close()

        collection = get_or_create_collection(
            self._weaviate.client,
            self._settings.weaviate_collection,
        )
        upload_chunks(
            collection,
            texts,
            vectors,
            metadata,
            ids=stable_ids,
        )
        clear_retrieval = getattr(
            self._rag_service,
            "clear_retrieval_cache",
            None,
        )
        if callable(clear_retrieval):
            clear_retrieval()
        clear_answers = getattr(
            self._llm_service,
            "clear_answer_cache",
            None,
        )
        if callable(clear_answers):
            clear_answers()
        return {
            "document_id": document_id,
            "chunk_count": len(chunks),
            "status": "indexed",
        }
