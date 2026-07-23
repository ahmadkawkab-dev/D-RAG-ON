"""FastAPI application factory and external-service lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from backend.api.v1.router import api_router
from backend.core.config import Settings, get_settings
from backend.db.mongodb import MongoManager
from backend.db.weaviate import WeaviateManager
from backend.services.fast_llm_service import FastLLMService
from backend.services.fast_rag_service import FastRAGService
from backend.services.general_chat_service import GeneralChatService


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    mongodb = MongoManager()
    weaviate = WeaviateManager()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = runtime_settings
        application.state.mongodb = mongodb
        application.state.active_generation_tasks = set()
        application.state.weaviate = weaviate
        application.state.rag_service = FastRAGService(
            runtime_settings,
            weaviate,
        )
        application.state.llm_service = FastLLMService(runtime_settings)
        application.state.general_chat_service = GeneralChatService(
            runtime_settings
        )
        try:
            if runtime_settings.connect_external_services_on_startup:
                await mongodb.connect(runtime_settings)
                await weaviate.connect(runtime_settings)
                if runtime_settings.keep_models_warm:
                    await application.state.llm_service.warm()
            yield
        finally:
            await weaviate.close()
            await mongodb.close()

    application = FastAPI(
        title=runtime_settings.app_name,
        debug=runtime_settings.debug,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(
        api_router,
        prefix=runtime_settings.api_v1_prefix,
    )

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
 
## uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000