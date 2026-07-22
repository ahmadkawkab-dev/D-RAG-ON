"""FastAPI dependency injection for settings, databases, services, and users."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from backend.core.config import Settings
from backend.core.security import InvalidTokenError, decode_token
from backend.models.user import UserDocument
from backend.services.chat_service import ChatService
from backend.services.email_service import EmailService
from backend.services.feedback_service import FeedbackService
from backend.services.general_chat_service import GeneralChatService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


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


def get_email_service(
    settings: Settings = Depends(get_app_settings),
) -> EmailService:
    return EmailService(settings)


def get_feedback_service(database: Any = Depends(get_db)) -> FeedbackService:
    return FeedbackService(database)


def get_chat_service(database: Any = Depends(get_db)) -> ChatService:
    return ChatService(database)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    database: Any = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> UserDocument:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_token(token, "access", settings)
    except InvalidTokenError as exc:
        raise credentials_error from exc
    document = await database.users.find_one({"_id": claims.sub})
    if document is None:
        raise credentials_error
    return UserDocument.model_validate(document)
