"""Internal, bounded PDF ingestion endpoint called only by .NET."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from backend.api.deps import get_internal_user_id
from backend.services.document_ingestion_service import (
    DocumentIngestionService,
)


router = APIRouter()
logger = logging.getLogger(__name__)
MAX_PDF_BYTES = 10 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


class DocumentUploadResponse(BaseModel):
    document_id: str
    chunk_count: int
    status: str


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    _user_id: str = Depends(get_internal_user_id),
) -> DocumentUploadResponse:
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Unsupported file content type")

    document_id = uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix="rag-upload-") as temp_dir:
            target = Path(temp_dir) / f"{document_id}.pdf"
            total = 0
            with target.open("wb") as output:
                while chunk := await file.read(READ_CHUNK_BYTES):
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="PDF exceeds the 10 MiB limit",
                        )
                    output.write(chunk)
            if total == 0:
                raise HTTPException(status_code=400, detail="PDF cannot be empty")
            with target.open("rb") as uploaded:
                if uploaded.read(5) != b"%PDF-":
                    raise HTTPException(
                        status_code=400,
                        detail="The uploaded file is not a valid PDF",
                    )

            service = DocumentIngestionService(
                request.app.state.settings,
                request.app.state.weaviate,
                request.app.state.rag_service,
                request.app.state.llm_service,
            )
            result = await asyncio.to_thread(
                service.ingest_pdf,
                target,
                document_id,
            )
            return DocumentUploadResponse.model_validate(result)
    except HTTPException:
        raise
    except ValueError as exception:
        raise HTTPException(status_code=400, detail="PDF could not be processed") from exception
    except Exception:
        logger.exception(
            "Document ingestion failed for trace %s",
            request.headers.get("X-Correlation-Id", "unavailable")[:128],
        )
        raise HTTPException(
            status_code=503,
            detail="Document ingestion is temporarily unavailable",
        )
    finally:
        await file.close()
