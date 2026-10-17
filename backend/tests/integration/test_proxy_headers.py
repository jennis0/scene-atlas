"""X-Forwarded-For sets the rate-limit key only on connections from a trusted proxy."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

TRUSTED_PROXY = ("127.0.0.1", 40000)  # FORWARDED_ALLOW_IPS default
UNTRUSTED_PEER = ("203.0.113.7", 40000)
LIMITED = "/api/v1/system/library"  # rate_limit_destructive: 1/minute


@pytest.fixture
def limited(test_client, monkeypatch):
    from backend.app.api.rate_limits import limiter
    from backend.app.config import settings

    monkeypatch.setattr(settings, "rate_limit_destructive", "1/minute")
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False


def _delete(peer: tuple[str, int], forwarded_for: str) -> int:
    # Without `with`, TestClient skips the lifespan; test_client already ran it.
    client = TestClient(app, client=peer)
    return client.delete(LIMITED, headers={"X-Forwarded-For": forwarded_for}).status_code


def test_trusted_proxy_keys_on_forwarded_client(limited):
    assert _delete(TRUSTED_PROXY, "198.51.100.1") != 429
    assert _delete(TRUSTED_PROXY, "198.51.100.2") != 429  # another client, own bucket
    assert _delete(TRUSTED_PROXY, "198.51.100.1") == 429


def test_untrusted_peer_cannot_choose_its_bucket(limited):
    assert _delete(UNTRUSTED_PEER, "198.51.100.1") != 429
    assert _delete(UNTRUSTED_PEER, "198.51.100.2") == 429


def test_spoofed_entries_left_of_the_proxy_are_ignored(limited):
    # A proxy that appends: the client-supplied entry comes first, the real one last.
    assert _delete(TRUSTED_PROXY, "10.9.9.9, 198.51.100.1") != 429
    assert _delete(TRUSTED_PROXY, "10.9.9.8, 198.51.100.1") == 429
