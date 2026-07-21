"""Central API v1 router."""

from fastapi import APIRouter

from backend.api.v1.endpoints import auth, chat, history


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(history.router, prefix="/history", tags=["history"])
