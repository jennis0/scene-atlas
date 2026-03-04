"""Tests that AUTH_TOKEN config is optional and defaults to None."""

from backend.app.config import Settings


def test_auth_token_defaults_to_none():
    s = Settings()
    assert s.auth_token is None


def test_auth_token_reads_from_env(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "my-secret-token")
    s = Settings()
    assert s.auth_token == "my-secret-token"
