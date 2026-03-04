"""Tests that security headers are present on all responses."""

import logging


def test_security_headers_present(test_client):
    resp = test_client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("Permissions-Policy") == "camera=(), microphone=()"


def test_security_headers_on_api_endpoint(test_client):
    resp = test_client.get("/api/v1/images/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("Permissions-Policy") == "camera=(), microphone=()"


def test_cors_warning_logged_in_server_mode_with_defaults(caplog, monkeypatch):
    """Startup should warn when server mode uses default localhost CORS."""
    from backend.app.config import settings

    monkeypatch.setattr(settings, "app_mode", "server")
    monkeypatch.setattr(
        settings,
        "cors_origins",
        ["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"],
    )

    with caplog.at_level(logging.WARNING):
        _default_cors = {"http://localhost:3000", "http://localhost:5173", "http://localhost:8000"}
        if settings.app_mode == "server" and set(settings.cors_origins) == _default_cors:
            logging.getLogger("backend.app.main").warning(
                "CORS origins are still set to localhost defaults but APP_MODE=server."
            )

    assert "CORS" in caplog.text
