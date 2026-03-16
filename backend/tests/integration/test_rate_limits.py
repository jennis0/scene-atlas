"""Tests for rate limiting middleware."""

import pytest
from fastapi.testclient import TestClient


def test_request_succeeds_under_limit(test_client: TestClient):
    """Smoke test: requests succeed when rate limiting is disabled in tests."""
    resp = test_client.get("/health")
    assert resp.status_code == 200


@pytest.fixture
def rate_limited_client(test_client: TestClient):
    """Re-enable rate limiting for a single test, then restore."""
    from backend.app.api.rate_limits import limiter

    limiter.enabled = True
    limiter.reset()
    yield test_client
    limiter.enabled = False


def test_rate_limit_returns_429(rate_limited_client: TestClient, monkeypatch):
    """Verify rate limiting actually blocks excess requests with 429."""
    from backend.app.config import settings

    monkeypatch.setattr(settings, "rate_limit_destructive", "1/minute")

    # First request should succeed (or 409 if no active purge job — either is fine)
    resp1 = rate_limited_client.delete("/api/v1/system/library")
    assert resp1.status_code in (200, 409)

    # Second request within the same minute should be rate-limited
    resp2 = rate_limited_client.delete("/api/v1/system/library")
    assert resp2.status_code == 429


# ── Per-endpoint smoke tests ──────────────────────────────────────────────────
# These verify that each rate-limited endpoint has a valid `request: Request`
# parameter (required by slowapi). If it's missing, slowapi raises a 500.
# We send one request with the limiter enabled and assert we do NOT get 500.


_RATE_LIMITED_ENDPOINTS = [
    ("DELETE", "/api/v1/system/library"),
    ("POST", "/api/v1/system/tags/reset"),
    ("POST", "/api/v1/search/rebuild-embeddings"),
    ("POST", "/api/v1/tags/retag-all"),
    ("POST", "/api/v1/images/backfill-grids"),
    ("PATCH", "/api/v1/settings/"),
    ("GET", "/api/v1/export/library"),
]


@pytest.mark.parametrize("method,path", _RATE_LIMITED_ENDPOINTS)
def test_rate_limited_endpoint_has_request_param(rate_limited_client: TestClient, method, path):
    """Each rate-limited endpoint must accept Request — no 500 from slowapi."""
    resp = rate_limited_client.request(method, path)
    assert resp.status_code != 500, (
        f"{method} {path} returned 500 — likely missing request: Request"
    )


def test_rate_limiting_disabled_allows_unlimited(test_client: TestClient):
    """When rate limiting is disabled (the test default), no requests are blocked.

    The test_client fixture sets limiter.enabled = False, simulating
    RATE_LIMIT_ENABLED=false in config.
    """
    from backend.app.api.rate_limits import limiter

    assert limiter.enabled is False, "test_client fixture should disable rate limiting"

    # Even rapid repeated calls to a rate-limited endpoint should succeed
    for _ in range(5):
        resp = test_client.get("/api/v1/export/library")
        # 200 = success, not 429 = rate-limited
        assert resp.status_code != 429
