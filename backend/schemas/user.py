"""Public user schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

from backend.models.user import UserDocument


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    created_at: datetime

    @classmethod
    def from_document(cls, user: UserDocument) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            created_at=user.created_at,
        )
