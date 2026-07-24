"""FastAPI dependency injection for internal service requests."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from backend.core.config import Settings
from backend.services.chat_service import ChatService
from backend.services.feedback_service import FeedbackService
from backend.services.general_chat_service import GeneralChatService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Any:
    return request.app.state.mongodb.database


def get_rag_service(request: Request) -> RAGService:
    return request.app.state.rag_service


def get_llm_service(request: Request) -> LLMService:
    return request.app.state.llm_service


def get_general_chat_service(request: Request) -> GeneralChatService:
    return request.app.state.general_chat_service


def get_feedback_service(database: Any = Depends(get_db)) -> FeedbackService:
    return FeedbackService(database)


def get_chat_service(database: Any = Depends(get_db)) -> ChatService:
    return ChatService(database)


async def get_internal_user_id(
    settings: Settings = Depends(get_app_settings),
    supplied_api_key: Annotated[
        str | None,
        Header(alias="X-RAG-API-Key"),
    ] = None,
    application_user_id: Annotated[
        str | None,
        Header(alias="X-Application-User-Id"),
    ] = None,
) -> str:
    configured = settings.internal_api_key
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal service authentication is not configured",
        )
    expected = configured.get_secret_value()
    if not supplied_api_key or not hmac.compare_digest(
        supplied_api_key.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal service credential",
        )
    if (
        not application_user_id
        or len(application_user_id) > 128
        or not application_user_id.replace("-", "").isalnum()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid application user context",
        )
    return application_user_id
