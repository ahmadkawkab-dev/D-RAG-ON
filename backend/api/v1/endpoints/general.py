"""Authenticated open-domain chat streaming, isolated from document RAG."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from backend.api.deps import (
    get_chat_service,
    get_current_user,
    get_general_chat_service,
)
from backend.models.user import UserDocument
from backend.schemas.chat import ChatRequest
from backend.services.chat_service import ChatService, SessionNotFoundError
from backend.services.general_chat_service import GeneralChatService
from backend.services.sse import encode_sse


logger = logging.getLogger(__name__)
router = APIRouter()
_END = object()


@router.post("/stream", response_class=StreamingResponse)
async def stream_general_chat(
    payload: ChatRequest,
    request: Request,
    current_user: UserDocument = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
    general_service: GeneralChatService = Depends(get_general_chat_service),
) -> StreamingResponse:
    try:
        session = await chat_service.get_or_create_session(
            user_id=current_user.id,
            session_id=payload.session_id,
            first_message=payload.message,
            mode="general",
        )
        if payload.regenerate_message_id:
            prompt_message = await chat_service.get_message(
                user_id=current_user.id,
                session_id=session.id,
                message_id=payload.regenerate_message_id,
            )
            if prompt_message.role != "user":
                raise SessionNotFoundError(payload.regenerate_message_id)
        else:
            prompt_message = await chat_service.append_message(
                session_id=session.id,
                role="user",
                content=payload.message,
            )
        version = await chat_service.next_version(
            session_id=session.id,
            reply_to_message_id=prompt_message.id,
        )
        _, stored_messages = await chat_service.get_session(
            user_id=current_user.id,
            session_id=session.id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="General chat session or message not found",
        ) from exc

    latest_versions: dict[str, Any] = {}
    for message in stored_messages:
        if message.role == "assistant" and message.reply_to_message_id:
            current = latest_versions.get(message.reply_to_message_id)
            if current is None or message.version > current.version:
                latest_versions[message.reply_to_message_id] = message
    history = []
    for message in stored_messages:
        if message.id == prompt_message.id:
            continue
        if message.role == "assistant" and message.reply_to_message_id:
            if message.reply_to_message_id == prompt_message.id or latest_versions.get(message.reply_to_message_id) != message:
                continue
        history.append({"role": message.role, "content": message.content})
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def produce() -> None:
        assistant_parts: list[str] = []
        sources: list[dict[str, Any]] = []
        try:
            await queue.put(
                encode_sse(
                    "started",
                    {
                        "session_id": session.id,
                        "chat_mode": "general",
                        "web_enabled": general_service.web_enabled,
                        "reply_to_message_id": prompt_message.id,
                        "version": version,
                    },
                )
            )
            async with request.app.state.rag_service.model_execution():
                prepared = await general_service.prepare(
                    prompt_message.content,
                    history,
                )
                sources = prepared.sources
                await queue.put(encode_sse("metadata", {"sources": sources}))
                async for token in general_service.stream(prepared):
                    assistant_parts.append(token)
                    await queue.put(
                        encode_sse("delta", {"content": token})
                    )

            assistant = await chat_service.append_message(
                session_id=session.id,
                role="assistant",
                content="".join(assistant_parts),
                sources=sources,
                reply_to_message_id=prompt_message.id,
                version=version,
            )
            await queue.put(
                encode_sse(
                    "done",
                    {
                        "session_id": session.id,
                        "message_id": assistant.id,
                        "reply_to_message_id": prompt_message.id,
                        "version": version,
                    },
                )
            )
        except Exception:
            logger.exception(
                "General chat generation failed for session %s", session.id
            )
            await queue.put(
                encode_sse(
                    "error",
                    {"detail": "Unable to complete the general-chat response"},
                )
            )
        finally:
            await queue.put(_END)

    task = asyncio.create_task(produce())
    request.app.state.active_generation_tasks.add(task)
    task.add_done_callback(request.app.state.active_generation_tasks.discard)

    async def events():
        try:
            while True:
                item = await queue.get()
                if item is _END:
                    break
                yield item
        except asyncio.CancelledError:
            logger.info(
                "Client left general chat %s; generation continues", session.id
            )
            raise

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
