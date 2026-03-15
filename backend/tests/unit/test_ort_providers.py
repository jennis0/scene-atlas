"""Unit tests for ONNX Runtime execution provider resolution."""

from unittest.mock import MagicMock, patch

import pytest

# ── resolve_providers ────────────────────────────────────────────────────────


class TestResolveProviders:
    """Test provider resolution logic."""

    @patch("onnxruntime.get_available_providers")
    def test_cpu_preference(self, mock_providers):
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("cpu")
        assert result == ["CPUExecutionProvider"]
        mock_providers.assert_not_called()

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=True)
    @patch("onnxruntime.get_available_providers", return_value=["CPUExecutionProvider"])
    def test_auto_with_cuda_available(self, _mock_avail, _mock_cuda):
        # CUDA detection uses _cuda_provider_available(), not get_available_providers()
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("auto")
        assert result == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=False)
    @patch(
        "onnxruntime.get_available_providers",
        return_value=["DmlExecutionProvider", "CPUExecutionProvider"],
    )
    def test_auto_with_directml_available(self, _mock_avail, _mock_cuda):
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("auto")
        assert result == ["DmlExecutionProvider", "CPUExecutionProvider"]

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=False)
    @patch(
        "onnxruntime.get_available_providers",
        return_value=["CoreMLExecutionProvider", "CPUExecutionProvider"],
    )
    def test_auto_with_coreml_available(self, _mock_avail, _mock_cuda):
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("auto")
        assert result == ["CoreMLExecutionProvider", "CPUExecutionProvider"]

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=True)
    @patch(
        "onnxruntime.get_available_providers",
        return_value=["DmlExecutionProvider", "CPUExecutionProvider"],
    )
    def test_auto_prefers_cuda_over_directml(self, _mock_avail, _mock_cuda):
        # CUDA takes priority — even when DML is in get_available_providers()
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("auto")
        assert result[0] == "CUDAExecutionProvider"

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=False)
    @patch("onnxruntime.get_available_providers", return_value=["CPUExecutionProvider"])
    def test_auto_cpu_only(self, _mock_avail, _mock_cuda):
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("auto")
        assert result == ["CPUExecutionProvider"]

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=True)
    @patch("onnxruntime.get_available_providers", return_value=["CPUExecutionProvider"])
    def test_explicit_cuda_available(self, _mock_avail, _mock_cuda):
        # Explicit "cuda" also uses _cuda_provider_available(), not get_available_providers()
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("cuda")
        assert result == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    @patch("backend.app.services.ort_providers._cuda_provider_available", return_value=False)
    @patch("onnxruntime.get_available_providers", return_value=["CPUExecutionProvider"])
    def test_explicit_cuda_not_available(self, _mock_avail, _mock_cuda):
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("cuda")
        assert result == ["CPUExecutionProvider"]

    @patch("onnxruntime.get_available_providers")
    def test_explicit_directml(self, mock_providers):
        from backend.app.services.ort_providers import resolve_providers

        mock_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        result = resolve_providers("directml")
        assert result == ["DmlExecutionProvider", "CPUExecutionProvider"]

    @patch("onnxruntime.get_available_providers")
    def test_explicit_coreml(self, mock_providers):
        from backend.app.services.ort_providers import resolve_providers

        mock_providers.return_value = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        result = resolve_providers("coreml")
        assert result == ["CoreMLExecutionProvider", "CPUExecutionProvider"]

    @patch("onnxruntime.get_available_providers")
    def test_unknown_preference_falls_back_to_cpu(self, mock_providers):
        from backend.app.services.ort_providers import resolve_providers

        result = resolve_providers("tpu")
        assert result == ["CPUExecutionProvider"]


# ── get_session_options ──────────────────────────────────────────────────────


class TestGetSessionOptions:
    """Test provider-specific session option tuning."""

    def test_cpu_thread_counts(self):
        from backend.app.services.ort_providers import get_session_options

        opts = get_session_options(["CPUExecutionProvider"])
        assert opts.intra_op_num_threads == 2
        assert opts.inter_op_num_threads == 1

    def test_cuda_thread_counts(self):
        from backend.app.services.ort_providers import get_session_options

        opts = get_session_options(["CUDAExecutionProvider", "CPUExecutionProvider"])
        assert opts.intra_op_num_threads == 4
        assert opts.inter_op_num_threads == 2

    def test_directml_thread_counts(self):
        from backend.app.services.ort_providers import get_session_options

        opts = get_session_options(["DmlExecutionProvider", "CPUExecutionProvider"])
        assert opts.intra_op_num_threads == 1
        assert opts.inter_op_num_threads == 1

    def test_coreml_thread_counts(self):
        from backend.app.services.ort_providers import get_session_options

        opts = get_session_options(["CoreMLExecutionProvider", "CPUExecutionProvider"])
        assert opts.intra_op_num_threads == 1
        assert opts.inter_op_num_threads == 1

    def test_empty_list_defaults_to_cpu(self):
        from backend.app.services.ort_providers import get_session_options

        opts = get_session_options([])
        assert opts.intra_op_num_threads == 2
        assert opts.inter_op_num_threads == 1


# ── create_session_with_fallback ─────────────────────────────────────────────


class TestCreateSessionWithFallback:
    """Test session creation with GPU→CPU fallback."""

    @patch("onnxruntime.InferenceSession")
    def test_success_returns_actual_providers(self, mock_session_cls):
        from backend.app.services.ort_providers import (
            create_session_with_fallback,
            get_session_options,
        )

        mock_session = MagicMock()
        mock_session.get_providers.return_value = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        mock_session_cls.return_value = mock_session

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        opts = get_session_options(providers)
        session, actual = create_session_with_fallback("model.onnx", providers, opts)

        assert session is mock_session
        assert actual == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    @patch("onnxruntime.InferenceSession")
    def test_success_returns_actual_when_provider_dropped(self, mock_session_cls):
        from backend.app.services.ort_providers import (
            create_session_with_fallback,
            get_session_options,
        )

        mock_session = MagicMock()
        # ORT silently drops the GPU provider
        mock_session.get_providers.return_value = ["CPUExecutionProvider"]
        mock_session_cls.return_value = mock_session

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        opts = get_session_options(providers)
        session, actual = create_session_with_fallback("model.onnx", providers, opts)

        assert session is mock_session
        assert actual == ["CPUExecutionProvider"]

    @patch("onnxruntime.InferenceSession")
    def test_gpu_failure_falls_back_to_cpu(self, mock_session_cls):
        from backend.app.services.ort_providers import (
            create_session_with_fallback,
            get_session_options,
        )

        mock_cpu_session = MagicMock()
        # First call (GPU) fails, second call (CPU) succeeds
        mock_session_cls.side_effect = [RuntimeError("CUDA not available"), mock_cpu_session]

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        opts = get_session_options(providers)
        session, actual = create_session_with_fallback("model.onnx", providers, opts)

        assert session is mock_cpu_session
        assert actual == ["CPUExecutionProvider"]

    @patch("onnxruntime.InferenceSession")
    def test_cpu_failure_raises(self, mock_session_cls):
        from backend.app.services.ort_providers import (
            create_session_with_fallback,
            get_session_options,
        )

        mock_session_cls.side_effect = RuntimeError("Model not found")

        providers = ["CPUExecutionProvider"]
        opts = get_session_options(providers)
        with pytest.raises(RuntimeError, match="Model not found"):
            create_session_with_fallback("model.onnx", providers, opts)


# ── is_gpu_provider ──────────────────────────────────────────────────────────


class TestIsGpuProvider:
    """Test GPU provider detection."""

    def test_cuda_is_gpu(self):
        from backend.app.services.ort_providers import is_gpu_provider

        assert is_gpu_provider(["CUDAExecutionProvider", "CPUExecutionProvider"]) is True

    def test_directml_is_gpu(self):
        from backend.app.services.ort_providers import is_gpu_provider

        assert is_gpu_provider(["DmlExecutionProvider", "CPUExecutionProvider"]) is True

    def test_coreml_is_gpu(self):
        from backend.app.services.ort_providers import is_gpu_provider

        assert is_gpu_provider(["CoreMLExecutionProvider", "CPUExecutionProvider"]) is True

    def test_cpu_is_not_gpu(self):
        from backend.app.services.ort_providers import is_gpu_provider

        assert is_gpu_provider(["CPUExecutionProvider"]) is False

    def test_empty_is_not_gpu(self):
        from backend.app.services.ort_providers import is_gpu_provider

        assert is_gpu_provider([]) is False


# ── ImportError handling ────────────────────────────────────────────────────


class TestOnnxruntimeNotInstalled:
    """Test behaviour when no onnxruntime variant is installed."""

    def test_resolve_providers_raises_helpful_import_error(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "onnxruntime":
                raise ImportError("No module named 'onnxruntime'")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            from backend.app.services import ort_providers

            # Force re-import inside the function
            with pytest.raises(ImportError, match="No onnxruntime package is installed"):
                ort_providers.resolve_providers("auto")
