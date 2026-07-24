"""Dedicated MongoDB feedback document; never stored in Weaviate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field

from backend.models.base import MongoDocument


class FeedbackDocument(MongoDocument):
    user_id: str
    message_id: str
    session_id: str
    mode: Literal["document", "general"]
    direction: Literal["up", "down"]
    chips: list[str] = Field(default_factory=list)
    comment: str = ""
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        message_id: str,
        session_id: str,
        mode: Literal["document", "general"],
        direction: Literal["up", "down"],
        chips: list[str],
        comment: str,
    ) -> "FeedbackDocument":
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            user_id=user_id,
            message_id=message_id,
            session_id=session_id,
            mode=mode,
            direction=direction,
            chips=chips,
            comment=comment,
            created_at=now,
            updated_at=now,
        )
