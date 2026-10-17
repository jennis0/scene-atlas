"""Tests for LoopbackHostMiddleware (DNS-rebinding protection in the desktop app)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_mode(monkeypatch):
    monkeypatch.setattr("backend.app.config.settings.app_mode", "app")


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:5173", "LOCALHOST", "[::1]:8000"])
def test_app_mode_accepts_loopback(test_client: TestClient, app_mode, host):
    assert test_client.get("/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example:8000", "testserver", "127.0.0.1.evil.example"])
def test_app_mode_rejects_other_hosts(test_client: TestClient, app_mode, host):
    assert test_client.get("/health", headers={"host": host}).status_code == 400


def test_server_mode_leaves_hosts_to_the_proxy(test_client: TestClient):
    assert test_client.get("/health", headers={"host": "maps.example"}).status_code == 200
