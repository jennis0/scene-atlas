"""Tests for LoopbackHostMiddleware: DNS rebinding and the launch token (desktop app)."""

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


TOKEN = "s3cret-launch-token"


@pytest.fixture
def with_token(app_mode, monkeypatch):
    monkeypatch.setattr("backend.app.config.settings.app_token", TOKEN)


def test_with_a_token_a_request_without_it_is_refused(test_client: TestClient, with_token):
    assert test_client.get("/health", headers={"host": "127.0.0.1:8000"}).status_code == 403


def test_with_a_token_the_app_gets_in(test_client: TestClient, with_token):
    headers = {"host": "127.0.0.1:8000", "x-scene-atlas-token": TOKEN}
    assert test_client.get("/health", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"x-scene-atlas-token": "wrong"},
        {"x-scene-atlas-token": TOKEN[:-1]},
        {"x-scene-atlas-token": ""},
        {"cookie": f"scene_atlas_token={TOKEN}"},  # only the header counts
    ],
)
def test_with_a_token_a_wrong_one_is_refused(test_client: TestClient, with_token, headers):
    response = test_client.get("/health", headers={"host": "127.0.0.1:8000", **headers})
    assert response.status_code == 403


def test_with_a_token_api_routes_are_refused_too(test_client: TestClient, with_token):
    response = test_client.get("/api/v1/library/move", headers={"host": "127.0.0.1"})
    assert response.status_code == 403


def test_the_host_check_comes_first(test_client: TestClient, with_token):
    headers = {"host": "evil.example", "x-scene-atlas-token": TOKEN}
    assert test_client.get("/health", headers=headers).status_code == 400


def test_server_mode_ignores_a_token(test_client: TestClient, monkeypatch):
    monkeypatch.setattr("backend.app.config.settings.app_token", TOKEN)
    assert test_client.get("/health").status_code == 200


def test_the_token_is_kept_out_of_the_settings_repr():
    from backend.app.config import Settings

    assert TOKEN not in repr(Settings(app_token=TOKEN))
