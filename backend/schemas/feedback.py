"""Feedback request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ALLOWED_FEEDBACK_CHIPS = {
    "Inaccurate",
    "Not relevant",
    "Missing citation",
    "Too long",
    "Off-topic",
    "Hallucinated",
}


class FeedbackRequest(BaseModel):
    direction: Literal["up", "down"]
    chips: list[str] = Field(default_factory=list, max_length=6)
    comment: str = Field(default="", max_length=2000)

    @field_validator("chips")
    @classmethod
    def validate_chips(cls, value: list[str]) -> list[str]:
        deduplicated = list(dict.fromkeys(value))
        invalid = set(deduplicated) - ALLOWED_FEEDBACK_CHIPS
        if invalid:
            raise ValueError("Unsupported feedback reason")
        return deduplicated


class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    session_id: str
    mode: Literal["document", "general"]
    direction: Literal["up", "down"]
    chips: list[str]
    comment: str
    created_at: datetime
    updated_at: datetime
