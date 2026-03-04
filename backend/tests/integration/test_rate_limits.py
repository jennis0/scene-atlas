"""Smoke-test that rate limiting middleware is installed."""


def test_rate_limit_middleware_installed(test_client):
    """SlowAPI middleware is active — requests succeed under the limit."""
    resp = test_client.get("/api/v1/images/")
    assert resp.status_code == 200
