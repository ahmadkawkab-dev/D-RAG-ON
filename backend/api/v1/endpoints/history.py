"""Authenticated chat-session listing, detail, and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_chat_service, get_current_user
from backend.models.chat import ChatMessageDocument, ChatSessionDocument
from backend.models.user import UserDocument
from backend.schemas.chat import (
    ChatMessageResponse,
    ChatSessionDetail,
    ChatSessionResponse,
    Citation,
    DeleteSessionResponse,
)
from backend.services.chat_service import ChatService, SessionNotFoundError


router = APIRouter()


def _session_response(session: ChatSessionDocument) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_response(message: ChatMessageDocument) -> ChatMessageResponse:
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
    )


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    current_user: UserDocument = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> list[ChatSessionResponse]:
    sessions = await chat_service.list_sessions(current_user.id)
    return [_session_response(session) for session in sessions]


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetail,
)
async def get_session(
    session_id: str,
    current_user: UserDocument = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatSessionDetail:
    try:
        session, messages = await chat_service.get_session(
            user_id=current_user.id,
            session_id=session_id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        ) from exc
    return ChatSessionDetail(
        session=_session_response(session),
        messages=[_message_response(message) for message in messages],
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=DeleteSessionResponse,
)
async def delete_session(
    session_id: str,
    current_user: UserDocument = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> DeleteSessionResponse:
    try:
        await chat_service.delete_session(
            user_id=current_user.id,
            session_id=session_id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        ) from exc
    return DeleteSessionResponse(deleted=True, session_id=session_id)
