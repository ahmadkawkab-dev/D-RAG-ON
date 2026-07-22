"""Authenticated profile, password, and usage endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_current_user, get_db
from backend.core.security import hash_password, verify_password
from backend.models.user import UserDocument
from backend.schemas.auth import MessageResponse
from backend.schemas.user import (
    ChangePasswordRequest,
    ProfileUpdateRequest,
    UsageResponse,
    UserResponse,
)


router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_profile(
    current_user: UserDocument = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.from_document(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: UserDocument = Depends(get_current_user),
    database: Any = Depends(get_db),
) -> UserResponse:
    updates: dict[str, Any] = {}
    if "full_name" in payload.model_fields_set:
        updates["full_name"] = payload.full_name
    if "avatar_url" in payload.model_fields_set:
        updates["avatar_url"] = payload.avatar_url
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": updates},
    )
    document = await database.users.find_one({"_id": current_user.id})
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User no longer exists",
        )
    return UserResponse.from_document(UserDocument.model_validate(document))


@router.post("/me/password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: UserDocument = Depends(get_current_user),
    database: Any = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if verify_password(payload.new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )
    await database.users.update_one(
        {"_id": current_user.id},
        {"$set": {"hashed_password": hash_password(payload.new_password)}},
    )
    return MessageResponse(message="Password updated")


@router.get("/me/usage", response_model=UsageResponse)
async def get_usage(
    current_user: UserDocument = Depends(get_current_user),
    database: Any = Depends(get_db),
) -> UsageResponse:
    sessions = [
        document
        async for document in database.chat_sessions.find(
            {"user_id": current_user.id}
        )
    ]
    messages = 0
    assistant_answers = 0
    for session in sessions:
        session_id = session["_id"]
        messages += await database.chat_messages.count_documents(
            {"session_id": session_id}
        )
        assistant_answers += await database.chat_messages.count_documents(
            {"session_id": session_id, "role": "assistant"}
        )
    return UsageResponse(
        conversations=len(sessions),
        messages=messages,
        assistant_answers=assistant_answers,
        feedback_submitted=await database.feedback.count_documents(
            {"user_id": current_user.id}
        ),
    )
