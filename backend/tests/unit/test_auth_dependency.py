"""Tests for the bearer-token auth dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import verify_auth
from backend.app.config import settings


@pytest.fixture
def auth_app():
    """Minimal FastAPI app with the auth dependency applied."""
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(verify_auth)])
    def protected():
        return {"ok": True}

    return app


def test_no_token_configured_allows_all(auth_app, monkeypatch):
    """When AUTH_TOKEN is unset, all requests pass through."""
    monkeypatch.setattr(settings, "auth_token", None)
    client = TestClient(auth_app)
    resp = client.get("/protected")
    assert resp.status_code == 200


def test_correct_token_allowed(auth_app, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "secret123")
    client = TestClient(auth_app)
    resp = client.get("/protected", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


def test_wrong_token_rejected(auth_app, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "secret123")
    client = TestClient(auth_app)
    resp = client.get("/protected", headers={"Authorization": "Bearer wrongtoken"})
    assert resp.status_code == 401


def test_missing_header_rejected(auth_app, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "secret123")
    client = TestClient(auth_app)
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_malformed_header_rejected(auth_app, monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "secret123")
    client = TestClient(auth_app)
    resp = client.get("/protected", headers={"Authorization": "Basic secret123"})
    assert resp.status_code == 401
