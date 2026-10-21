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

import functools
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import onnxruntime as ort

logger = logging.getLogger(__name__)

# CUDA 12 shared libraries that onnxruntime-gpu requires at runtime.
_CUDA_REQUIRED_LIBS = [
    "libcudart.so.12",
    "libcublas.so.12",
    "libcublasLt.so.12",
    "libcufft.so.11",
    "libcudnn.so.9",
]


# Each CUDA library is first loaded in a child process. With a broken GPU driver, loading
# one can crash the dynamic loader itself (seen with WSL's libcuda.so.1 after a GPU reset:
# an ld.so assertion), which ends the process with no exception to catch. The child exits
# 0 when the library loads and _LIB_MISSING when it can't be found.
_LIB_MISSING = 3
_LOAD_LIB = (
    "import ctypes, sys\n"
    "try:\n"
    "    ctypes.CDLL(sys.argv[1])\n"
    "except OSError:\n"
    f"    sys.exit({_LIB_MISSING})\n"
)
_LOAD_TIMEOUT_S = 60


@dataclass(frozen=True)
class CudaLibs:
    """The required CUDA libraries that can't be found, and those that crash on loading."""

    missing: tuple[str, ...] = ()
    crashed: tuple[str, ...] = ()


@functools.cache
def check_cuda_libs() -> CudaLibs:
    """Load each required CUDA library in a child process and report what failed.

    Cached: the answer holds until the backend restarts. Linux only, since the names are
    Linux sonames; frozen builds can't start a Python child and never ship onnxruntime-gpu,
    so they report nothing.
    """
    if sys.platform != "linux" or getattr(sys, "frozen", False):
        return CudaLibs()
    missing: list[str] = []
    crashed: list[str] = []
    for lib in _CUDA_REQUIRED_LIBS:
        try:
            code = subprocess.run(  # noqa: S603  # nosec B603: our interpreter, a fixed script
                [sys.executable, "-c", _LOAD_LIB, lib],
                capture_output=True,
                timeout=_LOAD_TIMEOUT_S,
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            code = None
        if code == _LIB_MISSING:
            missing.append(lib)
        elif code != 0:
            crashed.append(lib)
    return CudaLibs(tuple(missing), tuple(crashed))


def _cuda_provider_available() -> bool:
    """Return True if CUDAExecutionProvider is usable.

    ``ort.get_available_providers()`` must list it: if it doesn't, ORT can't initialise
    it and any session request silently falls back to CPU, even if the provider .so file
    exists on disk. And loading the CUDA libraries must not crash (``check_cuda_libs``):
    if it does, creating a CUDA session would take the whole backend down, so CPU is used.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        return False
    crashed = check_cuda_libs().crashed
    if crashed:
        logger.warning(
            "Loading %s crashed the test process, so the NVIDIA driver is probably in a bad "
            "state. Using the CPU instead. Restarting the machine (on WSL: wsl --shutdown) "
            "usually fixes it.",
            ", ".join(crashed),
        )
        return False
    return True


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
    """Ordered ORT providers to request for *preference* (best first, CPU last).

    *preference* is one of ``"auto"``, ``"cpu"``, ``"cuda"``, ``"directml"``, ``"coreml"``.
    Raises ImportError if no onnxruntime variant is installed.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        raise ImportError(
            "No onnxruntime package is installed. Install one of:\n"
            "  uv sync --extra cpu           # CPU inference (default)\n"
            "  uv sync --extra gpu           # NVIDIA CUDA\n"
            "  uv sync --extra gpu-directml  # DirectX 12 (Windows)\n"
            "See design/gpu-acceleration.md for details."
        ) from None

    preference = preference.strip().lower()

    if preference == "cpu":
        return ["CPUExecutionProvider"]

    # get_available_providers() can omit CUDAExecutionProvider on some platforms
    # (e.g. WSL2) even when CUDA actually works — so CUDA uses a separate probe.
    available = set(ort.get_available_providers())

    if preference == "auto":
        # CUDA: probe-based (get_available_providers() is unreliable for CUDA on WSL2)
        if _cuda_provider_available():
            logger.info("Auto-detected CUDA provider")
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        # DML / CoreML: platform checks are built into get_available_providers()
        for provider in ["DmlExecutionProvider", "CoreMLExecutionProvider"]:
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

    # For CUDA, use the same probe rather than get_available_providers()
    provider_available = (
        _cuda_provider_available() if provider == "CUDAExecutionProvider" else provider in available
    )
    if not provider_available:
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
    - CPU:      intra=one per physical core, inter=1 (see ``cpu_inference_threads``)
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
        sess_opts.intra_op_num_threads = cpu_inference_threads()
        sess_opts.inter_op_num_threads = 1

    return sess_opts


def cpu_inference_threads() -> int:
    """One thread per physical core.

    Was 2, to leave room for the web server; the server is mostly waiting on I/O, and on a
    6-core Ryzen 9 5900X (WSL) the medium model ran at 1.1 images/s on 2 threads, 2.1 on 6
    and 1.6 on 12: hyperthreads share the cores' vector units and only add contention.
    """
    import psutil

    physical = psutil.cpu_count(logical=False)
    if not physical:
        physical = max(1, (os.cpu_count() or 2) // 2)
    return max(1, physical)


def create_session_with_fallback(
    model_path: str | Path,
    providers: list[str],
    sess_opts: ort.SessionOptions,
) -> tuple[ort.InferenceSession, list[str]]:
    """Create an ``InferenceSession``, falling back to CPU on failure.

    Returns the session and the providers it was actually created with.
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
        return session, list(actual)
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

        if primary == "CUDAExecutionProvider":
            missing = check_cuda_libs().missing
            if missing:
                hints = ["Missing CUDA libraries: %s."]
                if any("cudnn" in lib for lib in missing):
                    hints.append(
                        "cuDNN 9 is required but not installed. "
                        "On Ubuntu/Debian: sudo apt install libcudnn9-cuda-12"
                    )
                if any("cublas" in lib or "cufft" in lib or "cudart" in lib for lib in missing):
                    hints.append(
                        "Install the CUDA 12 toolkit: https://developer.nvidia.com/cuda-12-toolkit"
                    )
                hints.append("See design/gpu-acceleration.md for full prerequisites.")
                logger.warning(" ".join(hints), ", ".join(missing))

        cpu_providers = ["CPUExecutionProvider"]
        cpu_opts = get_session_options(cpu_providers)
        session = ort.InferenceSession(model_path, cpu_opts, providers=cpu_providers)
        return session, cpu_providers


def is_gpu_provider(providers: list[str]) -> bool:
    """Return True if the primary (first) provider is GPU-backed."""
    if not providers:
        return False
    return providers[0] in _GPU_PROVIDERS
