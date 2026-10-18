"""Integration tests for /api/v1/models/ endpoints."""

from unittest.mock import MagicMock


class TestListModels:
    def test_list_models_returns_200(self, test_client):
        resp = test_client.get("/api/v1/models/")
        assert resp.status_code == 200

    def test_list_models_returns_three_models(self, test_client):
        data = test_client.get("/api/v1/models/").json()
        assert "models" in data
        assert len(data["models"]) == 3

    def test_list_models_includes_expected_names(self, test_client):
        data = test_client.get("/api/v1/models/").json()
        names = {m["name"] for m in data["models"]}
        assert names == {"small", "medium", "large"}

    def test_list_models_each_has_required_fields(self, test_client):
        data = test_client.get("/api/v1/models/").json()
        required_fields = {
            "name",
            "label",
            "description",
            "description_technical",
            "recommended_hardware",
            "approx_size_mb",
            "downloaded",
            "active",
        }
        for model in data["models"]:
            for field in required_fields:
                assert field in model, f"Model '{model.get('name')}' missing field '{field}'"

    def test_list_models_exactly_one_active(self, test_client):
        data = test_client.get("/api/v1/models/").json()
        active = [m for m in data["models"] if m["active"]]
        # There must be exactly one active model (the effective model name)
        assert len(active) == 1


class TestSetupStatus:
    def test_setup_status_returns_200(self, test_client):
        resp = test_client.get("/api/v1/models/setup-status")
        assert resp.status_code == 200

    def test_setup_status_has_required_fields(self, test_client):
        data = test_client.get("/api/v1/models/setup-status").json()
        for field in (
            "needs_model",
            "setup_completed",
            "model_activating",
            "recommended",
            "has_gpu",
            "gpu_provider",
        ):
            assert field in data

    def test_setup_status_not_completed_before_setup_complete(self, test_client):
        data = test_client.get("/api/v1/models/setup-status").json()
        assert data["setup_completed"] is False

    def test_setup_status_completed_after_setup_complete(self, test_client):
        # Mark setup as complete
        resp = test_client.post("/api/v1/models/setup-complete")
        assert resp.status_code == 200

        # Now check setup status
        data = test_client.get("/api/v1/models/setup-status").json()
        assert data["setup_completed"] is True

    def test_setup_status_recommended_is_valid_name(self, test_client):
        data = test_client.get("/api/v1/models/setup-status").json()
        assert data["recommended"] in ("small", "medium", "large")

    def test_setup_status_needs_model_is_bool(self, test_client):
        data = test_client.get("/api/v1/models/setup-status").json()
        assert isinstance(data["needs_model"], bool)

    def test_setup_status_reports_a_running_model_activation(self, test_client, monkeypatch):
        from backend.app.api import models as models_api

        class FakeRunner:
            def get_active_job_id(self, name):
                return "job-1" if name == "Activate model: large" else None

        assert test_client.get("/api/v1/models/setup-status").json()["model_activating"] is False
        monkeypatch.setattr(models_api, "get_job_runner", lambda: FakeRunner())
        assert test_client.get("/api/v1/models/setup-status").json()["model_activating"] is True

    def test_setup_status_has_gpu_is_bool(self, test_client):
        data = test_client.get("/api/v1/models/setup-status").json()
        assert isinstance(data["has_gpu"], bool)


class TestDownloadModelEndpoint:
    def test_download_unknown_model_returns_404(self, test_client):
        resp = test_client.post("/api/v1/models/does_not_exist/download")
        assert resp.status_code == 404

    def test_download_already_downloaded_returns_already_downloaded(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: True,
        )
        resp = test_client.post("/api/v1/models/small/download")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_downloaded"
        assert resp.json()["job_id"] is None

    def test_download_triggers_job_when_not_downloaded(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: False,
        )
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "job-xyz"
        monkeypatch.setattr("backend.app.api.models.get_job_runner", lambda: mock_runner)

        resp = test_client.post("/api/v1/models/small/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "downloading"
        assert data["job_id"] == "job-xyz"


class TestDeleteEmbeddings:
    def test_delete_active_model_embeddings_returns_409(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.get_effective_model_name",
            lambda: "small",
        )
        resp = test_client.delete("/api/v1/models/small/embeddings")
        assert resp.status_code == 409

    def test_delete_unknown_model_returns_404(self, test_client):
        resp = test_client.delete("/api/v1/models/unknown_model/embeddings")
        assert resp.status_code == 404

    def test_delete_inactive_model_embeddings_returns_204(self, test_client, monkeypatch):
        # "large" is inactive — deleting its embeddings should succeed
        monkeypatch.setattr(
            "backend.app.api.models.get_effective_model_name",
            lambda: "small",
        )

        deleted_collections = []

        mock_lancedb = MagicMock()
        mock_lancedb.delete_collection_by_name = lambda name: deleted_collections.append(name)
        monkeypatch.setattr(
            "backend.app.api.models.get_lancedb_service",
            lambda: mock_lancedb,
        )

        resp = test_client.delete("/api/v1/models/large/embeddings")
        assert resp.status_code == 204
        assert "embeddings_large" in deleted_collections


class TestEmbeddingStats:
    """Uses a real LanceDB so the table-existence check runs against the real client API."""

    def test_reports_existing_collection(self, test_client, monkeypatch, tmp_path):
        from backend.app.services.lancedb_service import LanceDBService

        svc = LanceDBService(path=tmp_path / "lancedb", collection_name="embeddings_large")
        svc.add_image_embedding(
            1, [0.1] * svc._vector_size, {"filename": "a", "author": "", "base_name": ""}
        )
        monkeypatch.setattr("backend.app.api.models.get_lancedb_service", lambda: svc)

        data = test_client.get("/api/v1/models/large/embeddings").json()
        assert data == {"collection_name": "embeddings_large", "vectors_count": 1, "exists": True}

        data = test_client.get("/api/v1/models/small/embeddings").json()
        assert data["exists"] is False
        svc.close()


class TestSetActiveModel:
    def test_set_active_model_invalid_name_returns_422(self, test_client):
        resp = test_client.post(
            "/api/v1/models/active",
            json={"model_name": "invalid_model_name"},
        )
        assert resp.status_code == 422

    def test_set_active_model_already_active_returns_already_active(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.get_effective_model_name",
            lambda: "small",
        )
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: True,
        )
        resp = test_client.post(
            "/api/v1/models/active",
            json={"model_name": "small"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_active"

    def test_set_active_model_valid_name_returns_job(self, test_client, monkeypatch):
        # Make "medium" appear to be the current model so we can switch to "small"
        monkeypatch.setattr(
            "backend.app.api.models.get_effective_model_name",
            lambda: "medium",
        )
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: True,
        )
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "activate-job-id"
        mock_runner.get_active_job_id.return_value = None
        monkeypatch.setattr("backend.app.api.models.get_job_runner", lambda: mock_runner)

        resp = test_client.post(
            "/api/v1/models/active",
            json={"model_name": "small"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == "activate-job-id"

        # Verify that _download_and_activate (not _download_only) was submitted
        submitted_fn = mock_runner.submit.call_args[0][0]
        assert submitted_fn.__name__ == "_download_and_activate"

    def test_set_active_model_missing_body_returns_422(self, test_client):
        resp = test_client.post("/api/v1/models/active", json={})
        assert resp.status_code == 422

    def test_set_active_model_insufficient_disk_space_returns_409(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.get_effective_model_name",
            lambda: "medium",
        )
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: False,
        )
        monkeypatch.setattr(
            "backend.app.api.models.check_disk_space",
            lambda name: (False, 375, 10),
        )
        resp = test_client.post(
            "/api/v1/models/active",
            json={"model_name": "small"},
        )
        assert resp.status_code == 409
        assert "disk space" in resp.json()["detail"].lower()


class TestSetupComplete:
    def test_setup_complete_returns_200(self, test_client):
        resp = test_client.post("/api/v1/models/setup-complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "setup_completed_at" in data

    def test_setup_complete_is_idempotent(self, test_client):
        resp1 = test_client.post("/api/v1/models/setup-complete")
        assert resp1.status_code == 200
        ts1 = resp1.json()["setup_completed_at"]

        resp2 = test_client.post("/api/v1/models/setup-complete")
        assert resp2.status_code == 200
        ts2 = resp2.json()["setup_completed_at"]

        # Both should succeed; the second call updates the timestamp
        assert ts1 is not None
        assert ts2 is not None


class TestDownloadModelDiskSpaceCheck:
    def test_download_insufficient_disk_space_returns_409(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: False,
        )
        monkeypatch.setattr(
            "backend.app.api.models.check_disk_space",
            lambda name: (False, 375, 10),
        )
        resp = test_client.post("/api/v1/models/small/download")
        assert resp.status_code == 409
        assert "disk space" in resp.json()["detail"].lower()

    def test_download_sufficient_disk_space_proceeds(self, test_client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.api.models.is_model_downloaded",
            lambda name: False,
        )
        monkeypatch.setattr(
            "backend.app.api.models.check_disk_space",
            lambda name: (True, 375, 10000),
        )
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "job-abc"
        monkeypatch.setattr("backend.app.api.models.get_job_runner", lambda: mock_runner)

        resp = test_client.post("/api/v1/models/small/download")
        assert resp.status_code == 200
        assert resp.json()["status"] == "downloading"
