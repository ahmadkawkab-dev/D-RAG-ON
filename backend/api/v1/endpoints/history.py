"""Authenticated chat-session listing, detail, and deletion."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_chat_service, get_internal_user_id, get_feedback_service
from backend.models.chat import ChatMessageDocument, ChatSessionDocument
from backend.schemas.chat import (
    ChatMessageResponse,
    ChatSessionDetail,
    ChatSessionResponse,
    Citation,
    DeleteSessionResponse,
)
from backend.services.chat_service import ChatService, SessionNotFoundError
from backend.services.feedback_service import FeedbackService
from backend.schemas.feedback import FeedbackResponse


router = APIRouter()


def _session_response(session: ChatSessionDocument) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        mode=session.mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_response(
    message: ChatMessageDocument,
    feedback: FeedbackResponse | None = None,
) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        sources=[
            Citation.model_validate(source.model_dump())
            for source in message.sources
        ],
        timestamp=message.timestamp,
        reply_to_message_id=message.reply_to_message_id,
        version=message.version,
        feedback=feedback,
    )


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    mode: Literal["document", "general"] | None = Query(default=None),
    user_id: str = Depends(get_internal_user_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> list[ChatSessionResponse]:
    sessions = await chat_service.list_sessions(user_id, mode)
    return [_session_response(session) for session in sessions]


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetail,
)
async def get_session(
    session_id: str,
    user_id: str = Depends(get_internal_user_id),
    chat_service: ChatService = Depends(get_chat_service),
    feedback_service: FeedbackService = Depends(get_feedback_service),
) -> ChatSessionDetail:
    try:
        session, messages = await chat_service.get_session(
            user_id=user_id,
            session_id=session_id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        ) from exc
    feedback_docs = await feedback_service.list_for_session(
        user_id=user_id,
        session_id=session_id,
    )
    feedback_by_message = {
        feedback.message_id: FeedbackResponse(**feedback.model_dump())
        for feedback in feedback_docs
    }
    return ChatSessionDetail(
        session=_session_response(session),
        messages=[
            _message_response(message, feedback_by_message.get(message.id))
            for message in messages
        ],
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=DeleteSessionResponse,
)
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_internal_user_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> DeleteSessionResponse:
    try:
        await chat_service.delete_session(
            user_id=user_id,
            session_id=session_id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        ) from exc
    return DeleteSessionResponse(deleted=True, session_id=session_id)
