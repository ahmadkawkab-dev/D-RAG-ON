"""MongoDB persistence and ownership checks for chat history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.models.chat import (
    ChatMessageDocument,
    ChatSessionDocument,
    CitationRecord,
)


class SessionNotFoundError(LookupError):
    """The session does not exist or is owned by another user."""


class ChatService:
    def __init__(self, database: Any) -> None:
        self.database = database

    @staticmethod
    def title_from_message(message: str) -> str:
        normalized = " ".join(message.split())
        if len(normalized) <= 80:
            return normalized
        return normalized[:79].rstrip() + "..."

    async def get_or_create_session(
        self,
        *,
        user_id: str,
        session_id: str | None,
        first_message: str,
    ) -> ChatSessionDocument:
        now = datetime.now(timezone.utc)
        if session_id:
            document = await self.database.chat_sessions.find_one(
                {"_id": session_id, "user_id": user_id}
            )
            if document is None:
                raise SessionNotFoundError(session_id)
            await self.database.chat_sessions.update_one(
                {"_id": session_id, "user_id": user_id},
                {"$set": {"updated_at": now}},
            )
            document["updated_at"] = now
            return ChatSessionDocument.model_validate(document)

        session = ChatSessionDocument.create(
            user_id=user_id,
            title=self.title_from_message(first_message),
        )
        await self.database.chat_sessions.insert_one(session.to_mongo())
        return session

    async def append_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        sources: list[dict] | None = None,
    ) -> ChatMessageDocument:
        citations = [
            CitationRecord.model_validate(source) for source in (sources or [])
        ]
        message = ChatMessageDocument.create(
            session_id=session_id,
            role=role,
            content=content,
            sources=citations,
        )
        await self.database.chat_messages.insert_one(message.to_mongo())
        await self.database.chat_sessions.update_one(
            {"_id": session_id},
            {"$set": {"updated_at": message.timestamp}},
        )
        return message

    async def list_sessions(self, user_id: str) -> list[ChatSessionDocument]:
        cursor = self.database.chat_sessions.find({"user_id": user_id}).sort(
            "updated_at", -1
        )
        return [
            ChatSessionDocument.model_validate(document)
            async for document in cursor
        ]

    async def get_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> tuple[ChatSessionDocument, list[ChatMessageDocument]]:
        document = await self.database.chat_sessions.find_one(
            {"_id": session_id, "user_id": user_id}
        )
        if document is None:
            raise SessionNotFoundError(session_id)
        cursor = self.database.chat_messages.find(
            {"session_id": session_id}
        ).sort("timestamp", 1)
        messages = [
            ChatMessageDocument.model_validate(message)
            async for message in cursor
        ]
        return ChatSessionDocument.model_validate(document), messages

    async def delete_session(self, *, user_id: str, session_id: str) -> None:
        document = await self.database.chat_sessions.find_one(
            {"_id": session_id, "user_id": user_id},
            {"_id": 1},
        )
        if document is None:
            raise SessionNotFoundError(session_id)
        await self.database.chat_messages.delete_many({"session_id": session_id})
        result = await self.database.chat_sessions.delete_one(
            {"_id": session_id, "user_id": user_id}
        )
        if result.deleted_count != 1:
            raise SessionNotFoundError(session_id)
