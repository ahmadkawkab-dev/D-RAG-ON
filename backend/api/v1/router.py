"""Internal API v1 routes called only by the .NET middle layer."""

from fastapi import APIRouter

from backend.api.v1.endpoints import chat, feedback, general, history


api_router = APIRouter()
api_router.include_router(chat.router, prefix="/chat", tags=["document chat"])
api_router.include_router(general.router, prefix="/general", tags=["general chat"])
api_router.include_router(history.router, prefix="/history", tags=["history"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
