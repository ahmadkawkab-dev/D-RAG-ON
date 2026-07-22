"""Public user, profile, and account-usage schemas."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from backend.models.user import UserDocument


_IMAGE_PREFIXES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/webp;base64,",
)
_MAX_AVATAR_BYTES = 512 * 1024


def _validate_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 UTF-8 bytes")
    return value


def _validate_avatar(value: str | None) -> str | None:
    if value is None:
        return None
    prefix = next((item for item in _IMAGE_PREFIXES if value.startswith(item)), None)
    if prefix is None:
        raise ValueError("Avatar must be a PNG, JPEG, or WebP image")
    try:
        decoded = base64.b64decode(value[len(prefix):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Avatar data is not valid base64") from exc
    if not decoded or len(decoded) > _MAX_AVATAR_BYTES:
        raise ValueError("Avatar must be no larger than 512 KB")
    return value


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    avatar_url: str | None = None
    created_at: datetime

    @classmethod
    def from_document(cls, user: UserDocument) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            created_at=user.created_at,
        )


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = None

    _avatar = field_validator("avatar_url")(_validate_avatar)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Full name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> "ProfileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        return self


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    _current_password_size = field_validator("current_password")(_validate_password)
    _new_password_size = field_validator("new_password")(_validate_password)


class UsageResponse(BaseModel):
    conversations: int
    messages: int
    assistant_answers: int
    feedback_submitted: int
