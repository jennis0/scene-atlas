"""Integration tests: auth dependency applied to real routers."""

from backend.app.config import settings


def test_unauthenticated_returns_401_when_token_set(test_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "integration-token")
    resp = test_client.get("/api/v1/images/")
    assert resp.status_code == 401


def test_correct_token_returns_200(test_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "integration-token")
    resp = test_client.get("/api/v1/images/", headers={"Authorization": "Bearer integration-token"})
    assert resp.status_code == 200


def test_wrong_token_returns_401(test_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "integration-token")
    resp = test_client.get("/api/v1/images/", headers={"Authorization": "Bearer WRONG"})
    assert resp.status_code == 401


def test_no_auth_configured_still_works(test_client, monkeypatch):
    """When AUTH_TOKEN is None, all requests pass (backwards compat)."""
    monkeypatch.setattr(settings, "auth_token", None)
    resp = test_client.get("/api/v1/images/")
    assert resp.status_code == 200


def test_health_endpoint_unauthenticated(test_client, monkeypatch):
    """Health check should not require auth (monitoring probes)."""
    monkeypatch.setattr(settings, "auth_token", "integration-token")
    resp = test_client.get("/health")
    assert resp.status_code == 200
