from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLIENT = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(
    encoding="utf-8"
)
AUTH_PANEL = (
    ROOT / "frontend" / "src" / "components" / "AuthPanel.tsx"
).read_text(encoding="utf-8")


def test_frontend_preserves_general_and_document_proxy_routing() -> None:
    assert "'/api/rag/general/stream'" in CLIENT
    assert "'/api/rag/document/stream'" in CLIENT
    assert "mode === 'general'" in CLIENT
    assert "http://localhost:8000" not in CLIENT


def test_frontend_has_no_python_auth_or_browser_refresh_token_storage() -> None:
    assert "/api/v1/auth" not in CLIENT
    assert "refresh_token" not in CLIENT
    assert "localStorage" not in CLIENT
    assert "sessionStorage" not in CLIENT
    assert "/api/auth/login/google" in CLIENT
    assert "Continue with Google" in AUTH_PANEL
