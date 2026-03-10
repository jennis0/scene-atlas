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
gpu-cuda = ["onnxruntime-gpu>=1.16.0,<2.0"]
gpu-directml = ["onnxruntime-directml>=1.16.0,<2.0"]

[tool.uv]
conflicts = [
    [{ extra = "cpu" }, { extra = "gpu-cuda" }, { extra = "gpu-directml" }],
]
```

Installation:
- **Server:** `uv sync --extra cpu` — CPU onnxruntime (required — onnxruntime is not in core deps)
- **Dev:** `uv sync --extra dev` — CPU onnxruntime (dev extra includes `scene-atlas[cpu]`)
- **Dev + CUDA:** `uv sync --extra dev --extra gpu-cuda` — CUDA onnxruntime
- **Dev + DirectML:** `uv sync --extra dev --extra gpu-directml` — DirectML onnxruntime

**Important:** A bare `uv sync` (no extras) does not install any onnxruntime variant. The application will fail at startup with a clear `ImportError` explaining which extra to install.

### Provider Priority

1. **CUDAExecutionProvider** — NVIDIA GPUs (requires `onnxruntime-gpu`)
2. **DmlExecutionProvider** — Any DirectX 12 GPU on Windows (requires `onnxruntime-directml`)
3. **CoreMLExecutionProvider** — macOS Apple Silicon (opportunistic, no extra deps)
4. **CPUExecutionProvider** — Always available fallback

### Fallback Strategy

Fallback occurs at **session creation only** — not at runtime inference. If the GPU provider rejects the model, `create_session_with_fallback()` catches the exception and recreates with CPU. No runtime re-creation is attempted because the `CLIPService` singleton has no lock protecting session replacement after `_clip_ready` is set.

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

### Developer Scripts

The `--device` CLI flag controls both ONNX provider and torch device in ablation/export scripts. Torch doesn't support DirectML natively, so `--device directml` uses CPU for torch and DirectML for ONNX.

## Consequences

- CPU remains the default — no breaking changes
- GPU users install the appropriate onnxruntime variant and set `INFERENCE_DEVICE`
- CoreML is opportunistic (no guarantee, no extra dependencies)
- Linux Electron has no GPU build (CUDA requires user toolkit install)
- TensorRT excluded (engine building overhead, overkill for these model sizes)

## Migration

The deprecated `CLIP_DEVICE` env var is detected at startup and logged with a warning pointing to `INFERENCE_DEVICE`.

## Validation

Before shipping GPU support, run `scripts/validate_directml.py` to check:
- FP16 model op compatibility with DirectML (no silent per-op CPU fallback)
- Actual throughput vs CPU baseline
