"""Authenticated assistant-response feedback endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_current_user, get_feedback_service
from backend.models.feedback import FeedbackDocument
from backend.models.user import UserDocument
from backend.schemas.feedback import FeedbackRequest, FeedbackResponse
from backend.services.chat_service import SessionNotFoundError
from backend.services.feedback_service import FeedbackService


router = APIRouter()


def feedback_response(feedback: FeedbackDocument) -> FeedbackResponse:
    return FeedbackResponse(**feedback.model_dump())


@router.put("/messages/{message_id}", response_model=FeedbackResponse)
async def save_feedback(
    message_id: str,
    payload: FeedbackRequest,
    current_user: UserDocument = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackResponse:
    try:
        feedback = await service.upsert(
            user_id=current_user.id,
            message_id=message_id,
            direction=payload.direction,
            chips=payload.chips,
            comment=payload.comment,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assistant message not found",
        ) from exc
    return feedback_response(feedback)
