"""MongoDB persistence and ownership checks for chat history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

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
        mode: Literal["document", "general"] = "document",
    ) -> ChatSessionDocument:
        now = datetime.now(timezone.utc)
        if session_id:
            query: dict[str, Any] = {"_id": session_id, "user_id": user_id}
            if mode == "general":
                query["mode"] = "general"
            else:
                query["$or"] = [
                    {"mode": "document"},
                    {"mode": {"$exists": False}},
                ]
            document = await self.database.chat_sessions.find_one(query)
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
            mode=mode,
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
        reply_to_message_id: str | None = None,
        version: int = 1,
    ) -> ChatMessageDocument:
        citations = [
            CitationRecord.model_validate(source) for source in (sources or [])
        ]
        message = ChatMessageDocument.create(
            session_id=session_id,
            role=role,
            content=content,
            sources=citations,
            reply_to_message_id=reply_to_message_id,
            version=version,
        )
        await self.database.chat_messages.insert_one(message.to_mongo())
        await self.database.chat_sessions.update_one(
            {"_id": session_id},
            {"$set": {"updated_at": message.timestamp}},
        )
        return message

    async def list_sessions(
        self,
        user_id: str,
        mode: Literal["document", "general"] | None = None,
    ) -> list[ChatSessionDocument]:
        query: dict[str, Any] = {"user_id": user_id}
        if mode == "general":
            query["mode"] = "general"
        elif mode == "document":
            query["$or"] = [
                {"mode": "document"},
                {"mode": {"$exists": False}},
            ]
        cursor = self.database.chat_sessions.find(query).sort("updated_at", -1)
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

    async def get_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatMessageDocument:
        session = await self.database.chat_sessions.find_one(
            {"_id": session_id, "user_id": user_id},
            {"_id": 1},
        )
        if session is None:
            raise SessionNotFoundError(session_id)
        document = await self.database.chat_messages.find_one(
            {"_id": message_id, "session_id": session_id}
        )
        if document is None:
            raise SessionNotFoundError(message_id)
        return ChatMessageDocument.model_validate(document)

    async def next_version(
        self,
        *,
        session_id: str,
        reply_to_message_id: str,
    ) -> int:
        document = await self.database.chat_messages.find_one(
            {
                "session_id": session_id,
                "role": "assistant",
                "reply_to_message_id": reply_to_message_id,
            },
            sort=[("version", -1)],
            projection={"version": 1},
        )
        return int(document.get("version", 1)) + 1 if document else 1

    async def delete_session(self, *, user_id: str, session_id: str) -> None:
        document = await self.database.chat_sessions.find_one(
            {"_id": session_id, "user_id": user_id},
            {"_id": 1},
        )
        if document is None:
            raise SessionNotFoundError(session_id)
        await self.database.chat_messages.delete_many({"session_id": session_id})
        await self.database.feedback.delete_many({"session_id": session_id})
        result = await self.database.chat_sessions.delete_one(
            {"_id": session_id, "user_id": user_id}
        )
        if result.deleted_count != 1:
            raise SessionNotFoundError(session_id)
