"""Compatibility entry point; the implementation lives in backend.main."""

from backend.main import app, create_app

__all__ = ["app", "create_app"]
