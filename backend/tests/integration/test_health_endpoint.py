"""Integration tests for GET /health and GET / (root endpoint).

Verifies the health endpoint returns the expected shape including mode field
and subsystem check results, and the root endpoint supports content negotiation.
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


class TestRootEndpoint:
    def test_returns_json_by_default(self, test_client):
        resp = test_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "app" in data

    def test_returns_json_when_accept_json(self, test_client):
        resp = test_client.get("/", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    def test_returns_html_in_server_mode_with_accept_html(self, test_client, monkeypatch):
        from backend.app.config import settings

        orig_mode = settings.app_mode
        settings.app_mode = "server"
        try:
            resp = test_client.get("/", headers={"Accept": "text/html"})
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            body = resp.text
            assert "Scene Atlas" in body
            assert "All systems operational" in body or "Some systems need attention" in body
            # Security: must not expose sensitive info
            assert "/api/v1/" in body
            assert "CORS" not in body
        finally:
            settings.app_mode = orig_mode

    def test_returns_json_in_app_mode_even_with_accept_html(self, test_client, monkeypatch):
        from backend.app.config import settings

        orig_mode = settings.app_mode
        settings.app_mode = "app"
        try:
            resp = test_client.get("/", headers={"Accept": "text/html"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "running"
        finally:
            settings.app_mode = orig_mode

    def test_html_status_page_does_not_expose_version(self, test_client, monkeypatch):
        """Security: the HTML status page must not expose version numbers."""
        from backend.app.config import settings

        orig_mode = settings.app_mode
        settings.app_mode = "server"
        try:
            resp = test_client.get("/", headers={"Accept": "text/html"})
            body = resp.text
            assert settings.app_version not in body
        finally:
            settings.app_mode = orig_mode
