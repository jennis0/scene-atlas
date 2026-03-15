"""ONNX Runtime execution provider resolution with session-creation fallback.

Selects the best available provider based on user preference (``INFERENCE_DEVICE``
env var) and what ONNX Runtime actually supports at runtime.  Falls back to CPU
if the requested GPU provider fails during ``InferenceSession`` construction.

Provider priority (auto mode):
  1. CUDAExecutionProvider   — NVIDIA GPUs (onnxruntime-gpu)
  2. DmlExecutionProvider    — Any DirectX 12 GPU on Windows (onnxruntime-directml)
  3. CoreMLExecutionProvider — macOS Apple Silicon (opportunistic)
  4. CPUExecutionProvider    — Always available

See ``design/gpu-acceleration.md`` for rationale.
"""

from __future__ import annotations

import ctypes
import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import onnxruntime as ort

logger = logging.getLogger(__name__)


def _preload_nvidia_cuda_libs() -> None:
    """Preload CUDA 12 shared libraries from nvidia pip packages if present.

    onnxruntime-gpu is compiled against CUDA 12 but the system may have a newer
    CUDA toolkit (e.g. 13.x) that doesn't provide libcublasLt.so.12.  Installing
    ``nvidia-cublas-cu12`` and ``nvidia-cudnn-cu12`` supplies those libraries as
    Python packages, but the dynamic linker won't find them automatically.  This
    function explicitly loads them with ctypes so they are resident in the process
    before onnxruntime's CUDA provider DSO is opened.
    """
    nvidia_packages = ["nvidia.cublas", "nvidia.cudnn"]
    for pkg in nvidia_packages:
        spec = importlib.util.find_spec(pkg)
        if spec is None or not spec.submodule_search_locations:
            continue
        lib_dir = Path(next(iter(spec.submodule_search_locations))) / "lib"
        if not lib_dir.is_dir():
            continue
        for so_file in sorted(lib_dir.glob("*.so.*")):
            try:
                ctypes.CDLL(str(so_file))
                logger.debug("Preloaded %s", so_file.name)
            except OSError as exc:
                logger.debug("Could not preload %s: %s", so_file.name, exc)


_preload_nvidia_cuda_libs()

# Provider name → friendly label for log messages
_GPU_PROVIDERS = {
    "CUDAExecutionProvider": "CUDA",
    "DmlExecutionProvider": "DirectML",
    "CoreMLExecutionProvider": "CoreML",
}

# Preference string → ORT provider name
_PREFERENCE_MAP = {
    "cuda": "CUDAExecutionProvider",
    "directml": "DmlExecutionProvider",
    "coreml": "CoreMLExecutionProvider",
}

# Auto-detection priority order
_AUTO_PRIORITY = [
    "CUDAExecutionProvider",
    "DmlExecutionProvider",
    "CoreMLExecutionProvider",
]


def resolve_providers(preference: str = "auto") -> list[str]:
    """Determine which ORT execution providers to request.

    Parameters
    ----------
    preference : str
        One of ``"auto"``, ``"cpu"``, ``"cuda"``, ``"directml"``, ``"coreml"``.

    Returns
    -------
    list[str]
        Ordered provider list (best first, CPU fallback last).

    Raises
    ------
    ImportError
        If no onnxruntime variant is installed.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        raise ImportError(
            "No onnxruntime package is installed. Install one of:\n"
            "  uv sync --extra cpu           # CPU inference (default)\n"
            "  uv sync --extra gpu-cuda       # NVIDIA CUDA\n"
            "  uv sync --extra gpu-directml   # DirectX 12 (Windows)\n"
            "See design/gpu-acceleration.md for details."
        ) from None

    preference = preference.strip().lower()

    if preference == "cpu":
        return ["CPUExecutionProvider"]

    available = set(ort.get_available_providers())

    if preference == "auto":
        for provider in _AUTO_PRIORITY:
            if provider in available:
                label = _GPU_PROVIDERS[provider]
                logger.info("Auto-detected %s provider", label)
                return [provider, "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    # Explicit GPU preference
    provider = _PREFERENCE_MAP.get(preference)
    if provider is None:
        logger.warning(
            "Unknown inference_device '%s'; falling back to CPU. "
            "Valid values: auto, cpu, cuda, directml, coreml",
            preference,
        )
        return ["CPUExecutionProvider"]

    if provider not in available:
        label = _GPU_PROVIDERS[provider]
        logger.warning(
            "%s provider requested but not available (installed providers: %s). "
            "Falling back to CPU.",
            label,
            ", ".join(sorted(available)),
        )
        return ["CPUExecutionProvider"]

    return [provider, "CPUExecutionProvider"]


def get_session_options(providers: list[str]) -> ort.SessionOptions:
    """Create session options tuned for the primary provider.

    Thread counts per provider:
    - CPU:      intra=2, inter=1  (avoid contention with uvicorn)
    - CUDA:     intra=4, inter=2  (feed the GPU pipeline)
    - DirectML: intra=1, inter=1  (async GPU dispatch, extra threads wasteful)
    - CoreML:   intra=1, inter=1  (same rationale as DirectML)
    """
    import onnxruntime as ort

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    primary = providers[0] if providers else "CPUExecutionProvider"

    if primary == "CUDAExecutionProvider":
        sess_opts.intra_op_num_threads = 4
        sess_opts.inter_op_num_threads = 2
    elif primary in ("DmlExecutionProvider", "CoreMLExecutionProvider"):
        sess_opts.intra_op_num_threads = 1
        sess_opts.inter_op_num_threads = 1
    else:
        # CPU
        sess_opts.intra_op_num_threads = 2
        sess_opts.inter_op_num_threads = 1

    return sess_opts


def create_session_with_fallback(
    model_path: str | Path,
    providers: list[str],
    sess_opts: ort.SessionOptions,
) -> tuple[ort.InferenceSession, list[str]]:
    """Create an ``InferenceSession``, falling back to CPU on failure.

    Parameters
    ----------
    model_path : str or Path
        Path to the ONNX model file.
    providers : list[str]
        Requested providers (from :func:`resolve_providers`).
    sess_opts : ort.SessionOptions
        Session options (from :func:`get_session_options`).

    Returns
    -------
    tuple[InferenceSession, list[str]]
        The session and the providers it was actually created with.
    """
    import onnxruntime as ort

    model_path = str(model_path)

    try:
        session = ort.InferenceSession(model_path, sess_opts, providers=providers)
        actual = session.get_providers()
        if actual != providers:
            logger.info(
                "Session for %s: requested %s, active %s",
                Path(model_path).name,
                providers,
                actual,
            )
        return session, actual
    except Exception as exc:
        if providers == ["CPUExecutionProvider"]:
            raise  # Already on CPU — nothing to fall back to

        primary = providers[0]
        label = _GPU_PROVIDERS.get(primary, primary)
        logger.warning(
            "%s session creation failed for %s: %s. Falling back to CPU.",
            label,
            Path(model_path).name,
            exc,
        )

        cpu_providers = ["CPUExecutionProvider"]
        cpu_opts = get_session_options(cpu_providers)
        session = ort.InferenceSession(model_path, cpu_opts, providers=cpu_providers)
        return session, cpu_providers


def is_gpu_provider(providers: list[str]) -> bool:
    """Return True if the primary (first) provider is GPU-backed."""
    if not providers:
        return False
    return providers[0] in _GPU_PROVIDERS
