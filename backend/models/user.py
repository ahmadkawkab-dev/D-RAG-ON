"""MongoDB user document."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import EmailStr

from backend.models.base import MongoDocument


class UserDocument(MongoDocument):
    email: EmailStr
    hashed_password: str
    full_name: str
    avatar_url: str | None = None
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        email: str,
        hashed_password: str,
        full_name: str,
    ) -> "UserDocument":
        return cls(
            id=str(uuid4()),
            email=email.lower(),
            hashed_password=hashed_password,
            full_name=full_name,
            avatar_url=None,
            created_at=datetime.now(timezone.utc),
        )
