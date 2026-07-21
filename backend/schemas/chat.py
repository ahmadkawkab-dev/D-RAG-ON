"""Chat, history, and citation API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceMetadata(BaseModel):
    document_id: str
    title: str
    source_url: str | None = None
    file_path: str | None = None
    page_number: int | None = None
    section: str | None = None

    model_config = ConfigDict(extra="ignore")


class Citation(SourceMetadata):
    chunk_text: str
    score: float | None = None
    relevance: float | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class ChatResponse(BaseModel):
    session_id: str
    content: str
    sources: list[Citation]


class ChatSessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[Citation]
    timestamp: datetime


class ChatSessionDetail(BaseModel):
    session: ChatSessionResponse
    messages: list[ChatMessageResponse]


class DeleteSessionResponse(BaseModel):
    deleted: bool
    session_id: str
