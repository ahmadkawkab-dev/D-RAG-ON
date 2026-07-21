"""User registration, OAuth2 password login, and refresh-token rotation."""

from __future__ import annotations

from typing import Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.errors import DuplicateKeyError

from backend.api.deps import get_app_settings, get_db
from backend.core.config import Settings
from backend.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.models.user import UserDocument
from backend.schemas.auth import (
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from backend.schemas.user import UserResponse


router = APIRouter()


def _tokens_for_user(user_id: str, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, settings),
        refresh_token=create_refresh_token(user_id, settings),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    database: Any = Depends(get_db),
) -> UserResponse:
    email = str(payload.email).lower()
    if await database.users.find_one({"email": email}, {"_id": 1}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    user = UserDocument.create(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    try:
        await database.users.insert_one(user.to_mongo())
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    return UserResponse.from_document(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    database: Any = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    email = form.username.strip().lower()
    document = await database.users.find_one({"email": email})
    if document is None or not verify_password(
        form.password,
        document.get("hashed_password", ""),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = UserDocument.model_validate(document)
    return _tokens_for_user(user.id, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshTokenRequest,
    database: Any = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    try:
        claims = decode_token(payload.refresh_token, "refresh", settings)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if await database.users.find_one({"_id": claims.sub}, {"_id": 1}) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _tokens_for_user(claims.sub, settings)
