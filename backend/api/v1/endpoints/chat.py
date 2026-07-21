"""Authenticated RAG chat streaming over Server-Sent Events."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from backend.api.deps import (
    get_chat_service,
    get_current_user,
    get_llm_service,
    get_rag_service,
)
from backend.models.user import UserDocument
from backend.schemas.chat import ChatRequest
from backend.services.chat_service import ChatService, SessionNotFoundError
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.sse import encode_sse


logger = logging.getLogger(__name__)
router = APIRouter()
ABSTENTION_RESPONSE = "Question irrelevant to the available document context."


@router.post("/stream", response_class=StreamingResponse)
async def stream_chat(
    payload: ChatRequest,
    current_user: UserDocument = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
    rag_service: RAGService = Depends(get_rag_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> StreamingResponse:
    try:
        session = await chat_service.get_or_create_session(
            user_id=current_user.id,
            session_id=payload.session_id,
            first_message=payload.message,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        ) from exc

    await chat_service.append_message(
        session_id=session.id,
        role="user",
        content=payload.message,
    )

    async def events():
        assistant_parts: list[str] = []
        source_payloads: list[dict] = []
        try:
            classify = getattr(rag_service, "is_complex_query", None)
            is_complex = bool(classify and classify(payload.message))
            yield encode_sse(
                "started",
                {
                    "session_id": session.id,
                    "mode": "complex" if is_complex else "fast",
                },
            )
            async with rag_service.model_execution():
                context = await rag_service.retrieve(payload.message)
                source_payloads = [
                    source.model_dump(mode="json")
                    for source in context.sources
                ]
                yield encode_sse("metadata", {"sources": source_payloads})

                if not context.is_relevant:
                    assistant_parts.append(ABSTENTION_RESPONSE)
                    yield encode_sse(
                        "delta",
                        {"content": ABSTENTION_RESPONSE},
                    )
                else:
                    answer_stream = (
                        llm_service.stream_answer(
                            payload.message,
                            context.chunks,
                            True,
                        )
                        if context.is_complex
                        else llm_service.stream_answer(payload.message, context.chunks)
                    )
                    async for token in answer_stream:
                        assistant_parts.append(token)
                        yield encode_sse("delta", {"content": token})

            assistant_content = "".join(assistant_parts)
            await chat_service.append_message(
                session_id=session.id,
                role="assistant",
                content=assistant_content,
                sources=source_payloads,
            )
            yield encode_sse("done", {"session_id": session.id})
        except asyncio.CancelledError:
            logger.info("Chat stream disconnected for session %s", session.id)
            raise
        except Exception:
            logger.exception("Chat stream failed for session %s", session.id)
            yield encode_sse(
                "error",
                {"detail": "Unable to complete the chat response"},
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
