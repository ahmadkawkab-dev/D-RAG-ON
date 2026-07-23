from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config import Settings
from backend.schemas.chat import ChatRequest


def test_internal_service_key_must_be_strong_when_configured() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(
            environment="test",
            connect_external_services_on_startup=False,
            internal_api_key="too-short",
        )


def test_production_requires_internal_service_authentication() -> None:
    with pytest.raises(ValidationError, match="required in production"):
        Settings(
            _env_file=None,
            environment="production",
            internal_api_key=None,
            connect_external_services_on_startup=False,
        )


def test_chat_request_rejects_whitespace_only_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")
