"""Tests for SecurityHeadersMiddleware."""

from fastapi.testclient import TestClient


def test_security_headers_on_200(test_client: TestClient):
    """All 4 security headers present on successful responses."""
    resp = test_client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["permissions-policy"] == "camera=(), microphone=()"


def test_security_headers_on_404(test_client: TestClient):
    """Security headers present on error responses too."""
    resp = test_client.get("/api/v1/images/999999/file")
    assert resp.status_code in (404, 422)
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["permissions-policy"] == "camera=(), microphone=()"
