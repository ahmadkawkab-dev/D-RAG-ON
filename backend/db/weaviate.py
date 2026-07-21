"""Managed connection to the existing synchronous Weaviate client."""

from __future__ import annotations

import asyncio

import weaviate
from weaviate import WeaviateClient

from backend.core.config import Settings


class WeaviateManager:
    def __init__(self) -> None:
        self._client: WeaviateClient | None = None

    @property
    def client(self) -> WeaviateClient:
        if self._client is None:
            raise RuntimeError("Weaviate has not been initialized")
        return self._client

    async def connect(self, settings: Settings) -> None:
        if self._client is not None:
            return

        def create_client() -> WeaviateClient:
            return weaviate.connect_to_custom(
                http_host=settings.weaviate_host,
                http_port=settings.weaviate_http_port,
                http_secure=settings.weaviate_secure,
                grpc_host=settings.weaviate_host,
                grpc_port=settings.weaviate_grpc_port,
                grpc_secure=settings.weaviate_secure,
            )

        client = await asyncio.to_thread(create_client)
        try:
            is_ready = await asyncio.to_thread(client.is_ready)
        except Exception:
            client.close()
            raise
        if not is_ready:
            client.close()
            raise RuntimeError("Weaviate is not ready")
        self._client = client

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
        self._client = None
