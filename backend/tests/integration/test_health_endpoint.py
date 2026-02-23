"""Integration tests for GET /health.

Verifies the health endpoint returns the expected shape including mode field
and subsystem check results.
"""


class TestHealthEndpoint:
    def test_returns_200(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code == 200

    def test_includes_mode(self, test_client):
        data = test_client.get("/health").json()
        assert "mode" in data
        assert data["mode"] in ("app", "server")

    def test_includes_status(self, test_client):
        data = test_client.get("/health").json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded")

    def test_includes_checks(self, test_client):
        data = test_client.get("/health").json()
        checks = data["checks"]
        assert "database" in checks
        assert "qdrant" in checks
        assert "job_runner" in checks
