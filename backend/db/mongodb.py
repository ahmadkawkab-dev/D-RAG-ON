"""Async MongoDB initialization and lifecycle management."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from backend.core.config import Settings


class MongoManager:
    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._database: AsyncIOMotorDatabase | None = None

    @property
    def database(self) -> AsyncIOMotorDatabase:
        if self._database is None:
            raise RuntimeError("MongoDB has not been initialized")
        return self._database

    async def connect(self, settings: Settings) -> None:
        if self._client is not None:
            return
        client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms,
            uuidRepresentation="standard",
        )
        try:
            await client.admin.command("ping")
            database = client[settings.mongodb_database]
            await self._create_indexes(database)
        except Exception:
            client.close()
            raise
        self._client = client
        self._database = database

    async def _create_indexes(self, database: AsyncIOMotorDatabase) -> None:
        await database.users.create_index(
            [("email", ASCENDING)],
            unique=True,
            name="users_email_unique",
        )
        await database.chat_sessions.create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="sessions_user_updated",
        )
        await database.chat_messages.create_index(
            [("session_id", ASCENDING), ("timestamp", ASCENDING)],
            name="messages_session_timestamp",
        )

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._database = None
