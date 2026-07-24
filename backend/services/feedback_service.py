"""MongoDB feedback persistence with message/session ownership checks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from backend.models.feedback import FeedbackDocument
from backend.services.chat_service import SessionNotFoundError


class FeedbackService:
    def __init__(self, database: Any) -> None:
        self.database = database

    async def upsert(
        self,
        *,
        user_id: str,
        message_id: str,
        direction: Literal["up", "down"],
        chips: list[str],
        comment: str,
    ) -> FeedbackDocument:
        message = await self.database.chat_messages.find_one(
            {"_id": message_id, "role": "assistant"},
            {"_id": 1, "session_id": 1},
        )
        if message is None:
            raise SessionNotFoundError(message_id)
        session = await self.database.chat_sessions.find_one(
            {"_id": message["session_id"], "user_id": user_id},
        )
        if session is None:
            raise SessionNotFoundError(message_id)

        existing = await self.database.feedback.find_one(
            {"user_id": user_id, "message_id": message_id}
        )
        now = datetime.now(timezone.utc)
        if existing is not None:
            await self.database.feedback.update_one(
                {"_id": existing["_id"], "user_id": user_id},
                {
                    "$set": {
                        "direction": direction,
                        "chips": chips,
                        "comment": comment,
                        "updated_at": now,
                    }
                },
            )
            existing.update(
                direction=direction,
                chips=chips,
                comment=comment,
                updated_at=now,
            )
            return FeedbackDocument.model_validate(existing)

        feedback = FeedbackDocument.create(
            user_id=user_id,
            message_id=message_id,
            session_id=message["session_id"],
            mode=session.get("mode", "document"),
            direction=direction,
            chips=chips,
            comment=comment,
        )
        await self.database.feedback.insert_one(feedback.to_mongo())
        return feedback

    async def list_for_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> list[FeedbackDocument]:
        cursor = self.database.feedback.find(
            {"user_id": user_id, "session_id": session_id}
        )
        return [
            FeedbackDocument.model_validate(document)
            async for document in cursor
        ]
