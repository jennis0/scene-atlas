# ADR: Optional GPU Acceleration for ONNX Runtime Inference

**Date:** 2026-03
**Status:** Accepted

## Context

Scene Atlas uses ONNX Runtime for ML inference (CLIP/SigLIP2 embedding models) during image ingest and search. As models grow larger (SigLIP2-SO400m is ~448MB) and ingest volumes increase, GPU acceleration significantly speeds up batch embedding generation.

## Decision

GPU acceleration is **opt-in** via the `INFERENCE_DEVICE` config setting (`auto`/`cpu`/`cuda`/`directml`/`coreml`). The default `auto` probes available ONNX Runtime execution providers and selects the best one.

### Package Strategy

`onnxruntime`, `onnxruntime-gpu`, and `onnxruntime-directml` are mutually exclusive PyPI packages. We use **uv conflict markers** to allow all three in one lockfile:

```toml
[project.optional-dependencies]
cpu = ["onnxruntime>=1.16.0,<2.0"]
cpu-dev = ["onnxruntime>=1.16.0,<2.0", "torch>=2.1.0,<3.0"]
gpu = ["onnxruntime-gpu>=1.16.0,<1.20"]
gpu-dev = ["onnxruntime-gpu>=1.16.0,<1.20", "torch>=2.1.0,<3.0"]
gpu-directml = ["onnxruntime-directml>=1.16.0,<2.0"]

[tool.uv]
conflicts = [
    [{ extra = "cpu" }, { extra = "cpu-dev" }, { extra = "gpu" }, { extra = "gpu-dev" }, { extra = "gpu-directml" }],
]
```

> **Note:** `onnxruntime-gpu` is pinned to `<1.20` because v1.20+ switched to a split-package model with a broken ABI (`undefined symbol: Provider_GetHost`). Re-evaluate after Microsoft fixes the split-package approach.

Installation:
- **Server (CPU):** `uv sync --extra cpu` — CPU onnxruntime only
- **Server (CUDA):** `uv sync --extra gpu` — CUDA onnxruntime
- **Server (DirectML):** `uv sync --extra gpu-directml` — DirectML onnxruntime
- **Dev (CPU):** `uv sync --extra dev --extra cpu-dev` — CPU onnxruntime + torch for model export
- **Dev (CUDA):** `uv sync --extra dev --extra gpu-dev` — CUDA onnxruntime + torch

The `-dev` variants add `torch`, needed for ONNX model export scripts. The non-dev variants are lighter (no torch).

**Important:** A bare `uv sync` (no extras) does not install any onnxruntime variant. The application will fail at startup with a clear `ImportError` explaining which extra to install.

### CUDA Prerequisites (Linux)

`onnxruntime-gpu` requires **both** the CUDA 12 toolkit **and** cuDNN 9 installed at the system level. The CUDA toolkit alone is not sufficient — cuDNN is a separate package.

```bash
# Ubuntu / Debian — add NVIDIA repo if not already present
# Replace ubuntu2404 with your distro version (ubuntu2204, ubuntu2004, etc.)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update

# Install cuDNN 9 for CUDA 12
sudo apt install libcudnn9-cuda-12

# Verify
ldconfig -p | grep libcudnn
# Should show: libcudnn.so.9 => /usr/lib/x86_64-linux-gnu/libcudnn.so.9
```

Required system libraries (all must be resolvable via `ldconfig`):
- `libcudart.so.12` — CUDA runtime (from `cuda-toolkit-12-*`)
- `libcublas.so.12` / `libcublasLt.so.12` — cuBLAS (from `libcublas-12-*`)
- `libcufft.so.11` — cuFFT (from `libcufft-12-*`)
- `libcudnn.so.9` — cuDNN (from `libcudnn9-cuda-12`)

If any are missing, onnxruntime will silently fall back to CPU. The application logs which libraries are missing when this happens.

### Provider Priority

1. **CUDAExecutionProvider** — NVIDIA GPUs (requires `onnxruntime-gpu`)
2. **DmlExecutionProvider** — Any DirectX 12 GPU on Windows (requires `onnxruntime-directml`)
3. **CoreMLExecutionProvider** — macOS Apple Silicon (opportunistic, no extra deps)
4. **CPUExecutionProvider** — Always available fallback

### Fallback Strategy

Two layers of protection:

1. **Session-creation fallback** — if the GPU provider rejects the model at load time, `create_session_with_fallback()` catches the exception and recreates with CPU.
2. **Runtime inference fallback** — if `.run()` fails on a GPU provider (e.g. DML command buffer exhaustion), `CLIPService._run_with_fallback()` recreates the session on CPU permanently and retries the failed inference.

### Known DirectML Limitations

DirectML leaks GPU memory on each `.run()` call (~517MB per call observed in [ORT #25996](https://github.com/microsoft/onnxruntime/issues/25996)). The command buffer accumulates until the GPU crashes with error `887A0006` (typically after ~110 sequential calls). There is no public API to flush/sync the DML command queue — session destruction is the only way to release resources.

**Mitigation:** `CLIPService._maybe_recreate_dml_session()` proactively recreates the DML session every 75 items processed (controlled by `_DML_SESSION_RECREATION_INTERVAL`). This is a workaround for a known, unresolved ORT issue — see [onnxruntime-genai #975](https://github.com/microsoft/onnxruntime-genai/issues/975), [onnxruntime #25996](https://github.com/microsoft/onnxruntime/issues/25996), [onnxruntime #10546](https://github.com/microsoft/onnxruntime/issues/10546). CUDA and CoreML are unaffected.

DirectML is in "sustained engineering" status (Microsoft shifting focus to Windows ML). If these issues are resolved upstream, the session recreation workaround can be removed.

### Session Options (Provider-Specific)

| Provider | `intra_op_threads` | `inter_op_threads` | Rationale |
|----------|--------------------|--------------------|-----------|
| CPU | 2 | 1 | Avoid contention with uvicorn |
| CUDA | 4 | 2 | Feed the GPU pipeline |
| DirectML | 1 | 1 | Async GPU dispatch; extra threads wasteful |
| CoreML | 1 | 1 | Same rationale as DirectML |

### Batch Size

Batch size is controlled by `PipelineConfig.ingestion_batch_size` (default: 16). Users can override this via the database `AppSettings` table. No provider-specific batch size adaptation is performed — users with high-VRAM GPUs can increase the batch size through settings.

## Architecture

### Key Files

- `backend/app/services/ort_providers.py` — Provider resolution, session options, fallback logic
- `backend/app/config.py` — `inference_device` setting (replaces deprecated `clip_device`)
- `backend/app/services/clip_service.py` — Uses resolver; exposes `active_providers` property
- `backend/pipeline/tasks/embedding_generation.py` — Provider-adaptive batch sizing

### Electron GPU Build (Windows DirectML)

A "Scene Atlas (GPU)" installer bundles `onnxruntime-directml`. DirectML works with any DirectX 12 GPU (NVIDIA, AMD, Intel) — no CUDA toolkit needed.

- **CI:** `GPU_VARIANT=directml` env var controls PyInstaller spec behaviour
- **Auto-update channels:** `latest` for CPU, `gpu` for GPU (prevents cross-update)
- **PyInstaller:** `DirectML.dll` and `onnxruntime_providers_dml.dll` added to `upx_exclude`

### DirectML Maintenance Status (as of 2026)

**DirectML is in maintenance-only mode.** The DirectML team was reassigned in mid-2025 (confirmed via [onnxruntime#23783](https://github.com/microsoft/onnxruntime/issues/23783)). Microsoft's active Windows GPU acceleration investment has moved to the Windows ML platform. DirectML continues to ship as a system DLL (`windows/system32/DirectML.dll`) for backwards compatibility and receives security updates, but will not gain new operators, performance improvements, or bug fixes.

**Do not invest in DirectML-specific optimisations** — they will not pay off.

#### Intel Integrated GPU Cold-Start Issue

Users with Intel integrated graphics (Iris Xe and similar) experience **25–180 second session creation times** on first DirectML launch due to shader compilation in ORT's `DmlGraphFusionTransformer`. This was reported in [onnxruntime#20502](https://github.com/microsoft/onnxruntime/issues/20502) and closed **NOT_PLANNED** by Microsoft in June 2025 — it will never be fixed.

- **NVIDIA discrete GPUs**: not affected (~600ms first launch)
- **AMD GPUs**: unknown, likely variable
- **Intel iGPU**: worst case, up to 3 minutes on first launch per process

Windows caches D3D12 PSOs after first run, so subsequent launches are fast. The first launch delay is unavoidable when using the DirectML GPU build on Intel hardware. This should be documented for end-users if/when the GPU installer ships.

### Developer Scripts

The `--device` CLI flag controls both ONNX provider and torch device in ablation/export scripts. Torch doesn't support DirectML natively, so `--device directml` uses CPU for torch and DirectML for ONNX.

## Consequences

- CPU remains the default — no breaking changes
- GPU users install the appropriate onnxruntime variant and set `INFERENCE_DEVICE`
- CoreML is opportunistic (no guarantee, no extra dependencies)
- Linux Electron has no GPU build (CUDA requires user toolkit + cuDNN install)
- TensorRT excluded (engine building overhead, overkill for these model sizes)

## Migration

The deprecated `CLIP_DEVICE` env var is detected at startup and logged with a warning pointing to `INFERENCE_DEVICE`.

## Validation

Before shipping GPU support, run `scripts/validate_directml.py` to check:
- FP16 model op compatibility with DirectML (no silent per-op CPU fallback)
- Actual throughput vs CPU baseline
