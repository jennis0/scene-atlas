"""Unit tests for backend.app.services.model_registry helpers."""

import pytest


class TestGetModel:
    def test_get_model_returns_entry_for_valid_name(self):
        from backend.app.services.model_registry import get_model

        entry = get_model("small")
        assert entry is not None
        assert entry["name"] == "small"

    def test_get_model_returns_entry_for_medium(self):
        from backend.app.services.model_registry import get_model

        entry = get_model("medium")
        assert entry is not None
        assert entry["name"] == "medium"

    def test_get_model_returns_entry_for_large(self):
        from backend.app.services.model_registry import get_model

        entry = get_model("large")
        assert entry is not None
        assert entry["name"] == "large"

    def test_get_model_returns_none_for_unknown(self):
        from backend.app.services.model_registry import get_model

        assert get_model("nonexistent") is None

    def test_get_model_returns_none_for_empty_string(self):
        from backend.app.services.model_registry import get_model

        assert get_model("") is None


class TestGetDefaultModel:
    def test_get_default_model_gpu_returns_medium(self):
        from backend.app.services.model_registry import get_default_model

        assert get_default_model(has_gpu=True) == "medium"

    def test_get_default_model_cpu_returns_small(self):
        from backend.app.services.model_registry import get_default_model

        assert get_default_model(has_gpu=False) == "small"


class TestHasRealGpuProvider:
    def test_has_real_gpu_provider_cuda_returns_true(self):
        from backend.app.services.clip_service import _has_real_gpu_provider

        assert _has_real_gpu_provider(["CUDAExecutionProvider", "CPUExecutionProvider"]) is True

    def test_has_real_gpu_provider_directml_returns_true(self):
        from backend.app.services.clip_service import _has_real_gpu_provider

        assert _has_real_gpu_provider(["DmlExecutionProvider", "CPUExecutionProvider"]) is True

    def test_has_real_gpu_provider_coreml_returns_true(self):
        from backend.app.services.clip_service import _has_real_gpu_provider

        assert _has_real_gpu_provider(["CoreMLExecutionProvider", "CPUExecutionProvider"]) is True

    def test_has_real_gpu_provider_cpu_only_returns_false(self):
        from backend.app.services.clip_service import _has_real_gpu_provider

        assert _has_real_gpu_provider(["CPUExecutionProvider"]) is False

    def test_has_real_gpu_provider_empty_returns_false(self):
        from backend.app.services.clip_service import _has_real_gpu_provider

        assert _has_real_gpu_provider([]) is False


class TestGpuProviderPriority:
    def test_gpu_provider_priority_contains_three_providers(self):
        from backend.app.services.model_registry import GPU_PROVIDER_PRIORITY

        assert len(GPU_PROVIDER_PRIORITY) == 3

    def test_gpu_provider_priority_ordering(self):
        from backend.app.services.model_registry import GPU_PROVIDER_PRIORITY

        assert GPU_PROVIDER_PRIORITY[0] == "CUDAExecutionProvider"
        assert GPU_PROVIDER_PRIORITY[1] == "DmlExecutionProvider"
        assert GPU_PROVIDER_PRIORITY[2] == "CoreMLExecutionProvider"

    def test_gpu_provider_priority_is_list(self):
        from backend.app.services.model_registry import GPU_PROVIDER_PRIORITY

        assert isinstance(GPU_PROVIDER_PRIORITY, list)


class TestAllModelsHaveRequiredFields:
    REQUIRED_FIELDS = [
        "name",
        "hf_repo",
        "label",
        "description",
        "description_technical",
        "recommended_hardware",
        "approx_size_mb",
        "model_id",
        "vision_quant",
        "text_quant",
    ]

    def test_all_models_present(self):
        from backend.app.services.model_registry import MODELS

        names = {m["name"] for m in MODELS}
        assert names == {"small", "medium", "large"}

    @pytest.mark.parametrize("field", REQUIRED_FIELDS)
    def test_all_models_have_field(self, field):
        from backend.app.services.model_registry import MODELS

        for model in MODELS:
            assert field in model, f"Model '{model.get('name')}' is missing field '{field}'"

    def test_approx_size_mb_is_positive_int(self):
        from backend.app.services.model_registry import MODELS

        for model in MODELS:
            assert isinstance(model["approx_size_mb"], int)
            assert model["approx_size_mb"] > 0

    def test_hf_repo_contains_namespace(self):
        from backend.app.services.model_registry import MODELS

        for model in MODELS:
            assert "/" in model["hf_repo"], f"hf_repo for '{model['name']}' has no namespace"
