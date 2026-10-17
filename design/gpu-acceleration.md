# ADR: GPU Acceleration for ONNX Runtime Inference

**Date:** 2026-03
**Status:** Accepted

## Context

Scene Atlas uses ONNX Runtime for ML inference (CLIP/SigLIP2 embedding models) during image ingest and search. GPU acceleration significantly speeds up batch embedding generation on large imports.

## Decision

The execution provider is selected by the `inference_device` setting (`INFERENCE_DEVICE` env var; `backend/app/config.py`). Values: `auto` (default), `cpu`, `cuda`, `directml`, `coreml`. `auto` uses the best available provider and falls back to CPU, so a GPU is used without configuration whenever the installed onnxruntime package supports it. Set `cpu` to force CPU.

An explicit provider that is unavailable, or an unknown value, logs a warning and resolves to CPU.

### Package Strategy

`onnxruntime`, `onnxruntime-gpu`, and `onnxruntime-directml` are mutually exclusive PyPI packages. They are separate extras in `pyproject.toml`, declared mutually exclusive via `[tool.uv] conflicts` so all can live in one lockfile:

| Extra | Package |
|---|---|
| `cpu` | `onnxruntime>=1.16.0,<2.0` |
| `cpu-dev` | `onnxruntime` + `torch` |
| `gpu` | `onnxruntime-gpu>=1.16.0,<1.20` |
| `gpu-dev` | `onnxruntime-gpu` + `torch` |
| `gpu-directml` | `onnxruntime-directml>=1.16.0,<2.0` |

> **Note:** `onnxruntime-gpu` is pinned to `<1.20` because 1.20+ is a split-package plugin with a broken ABI (`undefined symbol: Provider_GetHost`). Re-evaluate when Microsoft fixes the split-package model.

Installation:
- **Server (CPU):** `uv sync --extra cpu`
- **Server (CUDA):** `uv sync --extra gpu`
- **Server (DirectML):** `uv sync --extra gpu-directml`
- **Dev (CPU):** `uv sync --extra dev --extra cpu-dev`
- **Dev (CUDA):** `uv sync --extra dev --extra gpu-dev`

The `-dev` variants add `torch`, needed only by the ONNX export scripts.

A bare `uv sync` (no extras) installs no onnxruntime variant; `resolve_providers()` raises an `ImportError` naming the extras to install.

Desktop builds ship one package per platform (Windows: `onnxruntime-directml`; macOS and Linux: `onnxruntime`). See [electron.md](electron.md#gpu-support-in-desktop-builds).

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

Required system libraries (`_CUDA_REQUIRED_LIBS` in `ort_providers.py`):
- `libcudart.so.12` — CUDA runtime
- `libcublas.so.12` / `libcublasLt.so.12` — cuBLAS
- `libcufft.so.11` — cuFFT
- `libcudnn.so.9` — cuDNN

If the CUDA provider fails to initialise, the session falls back to CPU and the missing libraries are logged.

### Provider Priority (`auto`)

1. **CUDAExecutionProvider** — NVIDIA GPUs (requires `onnxruntime-gpu`)
2. **DmlExecutionProvider** — Any DirectX 12 GPU on Windows (requires `onnxruntime-directml`)
3. **CoreMLExecutionProvider** — macOS (included in the standard macOS wheel)
4. **CPUExecutionProvider** — Always available fallback

CUDA availability is probed with a separate check because `get_available_providers()` can omit CUDA on some platforms (e.g. WSL2) even when it works. The resolved list is always `[<gpu provider>, "CPUExecutionProvider"]` or `["CPUExecutionProvider"]`.

### Fallback Strategy

Two layers of protection:

1. **Session-creation fallback** — if the GPU provider rejects the model at load time, `create_session_with_fallback()` catches the exception and recreates the session on CPU.
2. **Runtime inference fallback** — if `.run()` fails on a GPU provider (e.g. DML command buffer exhaustion), `CLIPService._run_with_fallback()` replaces that session with a CPU session (it stays on CPU until the service is reloaded) and retries the failed inference.

### Known DirectML Limitations

DirectML leaks GPU memory on each `.run()` call ([ORT #25996](https://github.com/microsoft/onnxruntime/issues/25996)). The command buffer accumulates until the GPU fails with error `887A0006` (observed after ~110 sequential calls). There is no public API to flush the DML command queue — destroying the session is the only way to release resources.

**Mitigation:** `CLIPService._maybe_recreate_dml_session()` recreates a DML session after every 75 images or texts processed (`_DML_SESSION_RECREATION_INTERVAL` in `clip_service.py`). See also [onnxruntime-genai #975](https://github.com/microsoft/onnxruntime-genai/issues/975) and [onnxruntime #10546](https://github.com/microsoft/onnxruntime/issues/10546). CUDA and CoreML are unaffected.

### Session Options (Provider-Specific)

Set by `get_session_options()` from the primary provider:

| Provider | `intra_op_threads` | `inter_op_threads` | Rationale |
|----------|--------------------|--------------------|-----------|
| CPU | 2 | 1 | Avoid contention with uvicorn |
| CUDA | 4 | 2 | Feed the GPU pipeline |
| DirectML | 1 | 1 | Async GPU dispatch; extra threads wasteful |
| CoreML | 1 | 1 | Same rationale as DirectML |

### Batch Size

Embedding batch size is `PipelineConfig.ingestion_batch_size` (default 16), overridable through the `AppSettings` table. It does not vary by provider; users with high-VRAM GPUs can raise it in settings.

## Architecture

### Key Files

- `backend/app/services/ort_providers.py` — `resolve_providers()`, `get_session_options()`, `create_session_with_fallback()`, `is_gpu_provider()`, CUDA library check
- `backend/app/config.py` — `inference_device` setting
- `backend/app/services/clip_service.py` — resolves providers per session; runtime CPU fallback and DML session recreation

### DirectML Maintenance Status (as of 2026)

**DirectML is in maintenance-only mode.** The DirectML team was reassigned in mid-2025 ([onnxruntime#23783](https://github.com/microsoft/onnxruntime/issues/23783)); Microsoft's Windows GPU investment has moved to Windows ML. DirectML still ships and receives security updates but no new operators, performance work or bug fixes.

**Do not invest in DirectML-specific optimisations.** If the leak is fixed upstream, the session-recreation workaround can be removed.

#### Intel Integrated GPU Cold-Start Issue

Users with Intel integrated graphics (Iris Xe and similar) see **25–180 second session creation times** on first DirectML launch due to shader compilation in ORT's `DmlGraphFusionTransformer` ([onnxruntime#20502](https://github.com/microsoft/onnxruntime/issues/20502), closed NOT_PLANNED in June 2025).

- **NVIDIA discrete GPUs**: not affected (~600ms first launch)
- **AMD GPUs**: unknown, likely variable
- **Intel iGPU**: worst case, up to 3 minutes on first launch per process

Windows caches D3D12 PSOs after first run, so later launches are fast. Because the Windows desktop build always bundles DirectML, this affects Windows users on Intel iGPUs with `inference_device=auto`; setting it to `cpu` avoids it.

### Developer Scripts

`scripts/models/export_model_onnx.py --device {cpu,cuda,directml,coreml}` selects the ONNX provider for the optional quality evaluation. Export and quantisation always run on CPU; torch uses CUDA when available, and `directml` is ONNX-only.

## Consequences

- GPU is used automatically when the installed onnxruntime package provides a working provider; CPU is always the fallback
- Server users choose the onnxruntime variant via the uv extra
- CoreML is opportunistic (no guarantee, no extra dependencies)
- Linux desktop builds are CPU-only (CUDA would require a user-installed toolkit + cuDNN)
- TensorRT excluded (engine building overhead, overkill for these model sizes)
- The deprecated `CLIP_DEVICE` env var is ignored; if set, a warning pointing to `INFERENCE_DEVICE` is logged at startup

## Validation

`scripts/models/validate_directml.py` loads a model's vision and text encoders, runs synthetic inputs on DirectML and CPU, and reports:
- per-op CPU fallback warnings (FP16 op compatibility with DirectML)
- throughput vs the CPU baseline
