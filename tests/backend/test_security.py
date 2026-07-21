from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config import Settings
from backend.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.schemas.chat import ChatRequest


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        connect_external_services_on_startup=False,
        jwt_secret_key="test-secret-key-that-is-longer-than-32-bytes",
    )


def test_password_hash_round_trip() -> None:
    hashed = hash_password("correct-horse-battery-staple")

    assert hashed != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_and_refresh_tokens_are_not_interchangeable(
    settings: Settings,
) -> None:
    access = create_access_token("user-1", settings)
    refresh = create_refresh_token("user-1", settings)

    assert decode_token(access, "access", settings).sub == "user-1"
    assert decode_token(refresh, "refresh", settings).sub == "user-1"
    with pytest.raises(InvalidTokenError):
        decode_token(access, "refresh", settings)
    with pytest.raises(InvalidTokenError):
        decode_token(refresh, "access", settings)


def test_production_rejects_development_secret() -> None:
    with pytest.raises(ValidationError, match="must be changed"):
        Settings(environment="production")


def test_chat_request_rejects_whitespace_only_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")
