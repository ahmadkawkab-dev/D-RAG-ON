"""Chat, history, and citation API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.feedback import FeedbackResponse


class SourceMetadata(BaseModel):
    document_id: str
    title: str
    source_url: str | None = None
    file_path: str | None = None
    page_number: int | None = None
    section: str | None = None
    chunk_id: str | None = None
    breadcrumb: list[str] = Field(default_factory=list)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class Citation(SourceMetadata):
    chunk_text: str
    score: float | None = None
    relevance: float | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str | None = None

    regenerate_message_id: str | None = None
    model_config = ConfigDict(str_strip_whitespace=True)


class ChatResponse(BaseModel):
    session_id: str
    content: str
    sources: list[Citation]


class ChatSessionResponse(BaseModel):
    id: str
    title: str
    mode: Literal["document", "general"] = "document"
    created_at: datetime
    updated_at: datetime


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[Citation]
    timestamp: datetime

    reply_to_message_id: str | None = None
    version: int = 1
    feedback: FeedbackResponse | None = None


class ChatSessionDetail(BaseModel):
    session: ChatSessionResponse
    messages: list[ChatMessageResponse]


class DeleteSessionResponse(BaseModel):
    deleted: bool
    session_id: str
