"""MongoDB chat session and message documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.models.base import MongoDocument


class CitationRecord(BaseModel):
    document_id: str
    title: str
    source_url: str | None = None
    file_path: str | None = None
    chunk_text: str
    score: float | None = None
    relevance: float | None = None
    page_number: int | None = None
    section: str | None = None
    chunk_id: str | None = None
    breadcrumb: list[str] = Field(default_factory=list)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class ChatSessionDocument(MongoDocument):
    user_id: str
    mode: Literal["document", "general"] = "document"
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        title: str,
        mode: Literal["document", "general"] = "document",
    ) -> "ChatSessionDocument":
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            user_id=user_id,
            mode=mode,
            title=title,
            created_at=now,
            updated_at=now,
        )


class ChatMessageDocument(MongoDocument):
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[CitationRecord]
    timestamp: datetime
    reply_to_message_id: str | None = None
    version: int = 1

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        role: Literal["user", "assistant"],
        content: str,
        sources: list[CitationRecord] | None = None,
        reply_to_message_id: str | None = None,
        version: int = 1,
    ) -> "ChatMessageDocument":
        return cls(
            id=str(uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            sources=sources or [],
            timestamp=datetime.now(timezone.utc),
            reply_to_message_id=reply_to_message_id,
            version=version,
        )
