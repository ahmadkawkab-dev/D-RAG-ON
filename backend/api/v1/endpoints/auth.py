"""User registration, login, refresh, and password-reset flows."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.errors import DuplicateKeyError

from backend.api.deps import get_app_settings, get_db, get_email_service
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
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from backend.schemas.user import UserResponse
from backend.services.email_service import EmailConfigurationError, EmailService


logger = logging.getLogger(__name__)
router = APIRouter()
_RESET_RESPONSE = MessageResponse(
    message="If that account exists, a password reset code has been sent."
)


def _tokens_for_user(user_id: str, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, settings),
        refresh_token=create_refresh_token(user_id, settings),
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _reset_code_digest(
    email: str,
    code: str,
    settings: Settings,
) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        f"{email}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _invalid_reset_code() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="The reset code is invalid or has expired",
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


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    database: Any = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    email_service: EmailService = Depends(get_email_service),
) -> MessageResponse:
    try:
        email_service.ensure_available()
    except EmailConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset email is not configured",
        ) from exc

    email = str(payload.email).strip().lower()
    user = await database.users.find_one({"email": email}, {"_id": 1})
    if user is None:
        return _RESET_RESPONSE

    now = datetime.now(timezone.utc)
    existing = await database.password_reset_codes.find_one({"email": email})
    if (
        existing
        and existing.get("created_at")
        and existing["created_at"]
        > now - timedelta(seconds=settings.password_reset_resend_seconds)
    ):
        return _RESET_RESPONSE

    code = f"{secrets.randbelow(1_000_000):06d}"
    record = {
        "_id": str(uuid4()),
        "email": email,
        "code_digest": _reset_code_digest(email, code, settings),
        "attempts": 0,
        "created_at": now,
        "expires_at": now + timedelta(
            minutes=settings.password_reset_expire_minutes
        ),
    }
    await database.password_reset_codes.delete_many({"email": email})
    await database.password_reset_codes.insert_one(record)
    try:
        await email_service.send_password_reset_code(
            email,
            code,
            settings.password_reset_expire_minutes,
        )
    except Exception as exc:
        await database.password_reset_codes.delete_many({"email": email})
        logger.exception("Unable to send password reset email")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send the password reset email",
        ) from exc
    return _RESET_RESPONSE


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
)
async def confirm_password_reset(
    payload: PasswordResetConfirm,
    database: Any = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> MessageResponse:
    email = str(payload.email).strip().lower()
    record = await database.password_reset_codes.find_one({"email": email})
    now = datetime.now(timezone.utc)
    if record is None or record.get("expires_at") is None:
        raise _invalid_reset_code()
    if record["expires_at"] <= now:
        await database.password_reset_codes.delete_many({"email": email})
        raise _invalid_reset_code()

    attempts = int(record.get("attempts", 0))
    expected = _reset_code_digest(email, payload.code, settings)
    if attempts >= settings.password_reset_max_attempts or not hmac.compare_digest(
        expected,
        str(record.get("code_digest", "")),
    ):
        attempts += 1
        if attempts >= settings.password_reset_max_attempts:
            await database.password_reset_codes.delete_many({"email": email})
        else:
            await database.password_reset_codes.update_one(
                {"_id": record["_id"]},
                {"$set": {"attempts": attempts}},
            )
        raise _invalid_reset_code()

    result = await database.users.update_one(
        {"email": email},
        {"$set": {"hashed_password": hash_password(payload.new_password)}},
    )
    await database.password_reset_codes.delete_many({"email": email})
    if result.matched_count != 1:
        raise _invalid_reset_code()
    return MessageResponse(message="Password reset complete")
