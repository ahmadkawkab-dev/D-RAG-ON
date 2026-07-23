"""Authenticated open-domain chat streaming, isolated from document RAG."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from backend.api.deps import (
    get_chat_service,
    get_internal_user_id,
    get_general_chat_service,
)
from backend.schemas.chat import AnswerSelectionRequest, ChatMessageResponse, ChatRequest, Citation
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
    user_id: str = Depends(get_internal_user_id),
    chat_service: ChatService = Depends(get_chat_service),
    general_service: GeneralChatService = Depends(get_general_chat_service),
) -> StreamingResponse:
    try:
        session = await chat_service.get_or_create_session(
            user_id=user_id,
            session_id=payload.session_id,
            first_message=payload.message,
            mode="general",
        )
        if payload.regenerate_message_id:
            prompt_message = await chat_service.get_message(
                user_id=user_id,
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
            user_id=user_id,
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
        requires_selection = False
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
                await queue.put(
                    encode_sse(
                        "metadata",
                        {
                            "sources": sources,
                            "generation_id": prepared.generation_id,
                            "answer_count": prepared.answer_count,
                        },
                    )
                )
                async for event in general_service.stream_candidates(prepared):
                    event_payload = {
                        **event,
                        "session_id": session.id,
                        "reply_to_message_id": prompt_message.id,
                        "version": version,
                    }
                    event_type = str(event["type"])
                    if event_type == "token":
                        if prepared.answer_count == 1:
                            assistant_parts.append(str(event["content"]))
                            await queue.put(
                                encode_sse("delta", {"content": event["content"]})
                            )
                        else:
                            await queue.put(
                                encode_sse("candidate_delta", event_payload)
                            )
                    elif event_type in {
                        "generation_start",
                        "answer_start",
                        "answer_done",
                        "answer_error",
                        "generation_done",
                    }:
                        await queue.put(encode_sse(event_type, event_payload))
                        if event_type == "generation_done" and prepared.answer_count > 1:
                            requires_selection = bool(event.get("available_answer_ids"))

            if requires_selection:
                await queue.put(
                    encode_sse(
                        "done",
                        {
                            "session_id": session.id,
                            "message_id": None,
                            "reply_to_message_id": prompt_message.id,
                            "version": version,
                            "requires_selection": True,
                        },
                    )
                )
                return

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

@router.post("/answers/select", response_model=ChatMessageResponse)
async def select_general_answer(
    payload: AnswerSelectionRequest,
    user_id: str = Depends(get_internal_user_id),
    chat_service: ChatService = Depends(get_chat_service),
    general_service: GeneralChatService = Depends(get_general_chat_service),
) -> ChatMessageResponse:
    try:
        prompt_message = await chat_service.get_message(
            user_id=user_id,
            session_id=payload.session_id,
            message_id=payload.reply_to_message_id,
        )
        if prompt_message.role != "user":
            raise SessionNotFoundError(payload.reply_to_message_id)
        selected = general_service.get_selected_answer(
            generation_id=payload.generation_id,
            answer_id=payload.answer_id,
        )
        version = await chat_service.next_version(
            session_id=payload.session_id,
            reply_to_message_id=payload.reply_to_message_id,
        )
        assistant = await chat_service.append_message(
            session_id=payload.session_id,
            role="assistant",
            content=selected["content"],
            sources=selected["sources"],
            reply_to_message_id=payload.reply_to_message_id,
            version=version,
        )
    except (KeyError, SessionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated answer selection was not found",
        ) from exc

    return ChatMessageResponse(
        id=assistant.id,
        session_id=assistant.session_id,
        role="assistant",
        content=assistant.content,
        sources=[
            Citation.model_validate(source.model_dump())
            for source in assistant.sources
        ],
        timestamp=assistant.timestamp,
        reply_to_message_id=assistant.reply_to_message_id,
        version=assistant.version,
        feedback=None,
    )