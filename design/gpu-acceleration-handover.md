# GPU Acceleration Implementation Handover

> This document is a complete handover for implementing optional GPU acceleration in Scene Atlas. It contains the implementation plan, critical context about the codebase, pitfalls discovered during review, and explicit warnings about things that will break if done wrong.

---

## 1. What We're Building

Scene Atlas uses ONNX Runtime for ML inference (CLIP/SigLIP2 embedding models) during image ingest and search. Currently all inference is CPU-only, hardcoded in two places. We're adding optional GPU acceleration across all deployment modes:

- **Server/developer:** Install a GPU onnxruntime variant, set `INFERENCE_DEVICE=auto`
- **Electron app (Windows):** Separate "Scene Atlas (GPU)" installer using DirectML (works with any DirectX 12 GPU — no CUDA needed)
- **macOS:** Opportunistic CoreML auto-detection (no separate build needed)

The change must be backward-compatible: existing CPU workflows must work unchanged.

---

## 2. Codebase Context You Must Understand

### Model inference architecture
- `backend/app/services/clip_service.py` — The core inference service. **Singleton** loaded in a background thread via `start_clip_background_load()` (called at FastAPI startup). Uses `_clip_lock` mutex and `_clip_ready` threading.Event for thread safety. Once loaded, `get_clip_service()` returns the instance without locking.
- `backend/app/services/__init__.py` — Exposes `get_clip_service()` used by the rest of the app.
- Lines 214-220 of `clip_service.py` are the critical section: hardcoded `sess_opts` and `providers = ["CPUExecutionProvider"]`.
- Two ONNX sessions are created: `_vision_session` and `_text_session`, each from separate ONNX files.

### Quantisation/ablation scripts
- `scripts/quantisation/utils.py` — Shared utilities. `create_ort_session()` at line 72-86 has the second hardcoded `CPUExecutionProvider`. This function is used by ablation scripts.
- `scripts/quantisation/ablation_clip.py` and `ablation_siglip2.py` — Run ablation experiments. Load torch models via `AutoModel.from_pretrained()` with no explicit device (defaults to CPU). Use torch for reference embeddings, ONNX for test embeddings.
- `scripts/export_model_onnx.py` — Exports torch models to ONNX, quantises per model strategy, and optionally evaluates quality (gated behind `--image-dir`). Uses torch for sanity checks. `torch.onnx.export` requires CPU tensors. Evaluation functionality (previously in `scripts/evaluate_onnx.py`) is now absorbed here.

### Configuration
- `backend/app/config.py` — Pydantic `Settings` class. Line 51: `clip_device: str = "cpu"` exists but is **completely unused** — nothing reads it. Must be removed cleanly.
- `CLIP_DEVICE` is referenced in `.env.example:27`, `design/decisions.md:69`, `design/backend.md:271`, `README.md:142` — all must be updated.
- Settings uses `extra="ignore"` so stale env vars are silently discarded (won't error, but won't work either).

### Batch size
- `backend/pipeline/tasks/embedding_generation.py` — `batch_generate_clip_embeddings()` reads batch_size from `PipelineConfig().ingestion_batch_size` (default 16) when `batch_size is None`.
- `PipelineConfig.from_app_settings` reads from the `AppSettings` database table. User DB values take precedence over defaults.
- `CLIPService` currently does NOT expose which provider is active — you must add an `active_providers` property.

### PyInstaller / Electron packaging
- `backend/pyinstaller/scene_atlas_backend.spec` — Lines 168-174 strip all `.dist-info` directories. Comment explicitly warns: "If GPU or other plugin-based providers are ever added, revisit this filter."
- `collect_dynamic_libs('onnxruntime')` collects whatever DLLs exist in the installed package. If `onnxruntime-directml` is installed, it will pick up `onnxruntime_providers_dml.dll` and `DirectML.dll` automatically.
- Lines 199/216: `strip=True` and `upx=True` — may corrupt DirectML DLLs. Add them to `upx_exclude`.
- `electron-builder.yml` — Uses `publish.provider: github`. Auto-updater uses `latest.yml` feed file.
- `electron/src/main.ts` — Has `autoUpdater` integration. The update channel must be set at build time.

### CI workflows
- `.github/workflows/electron-build.yml` — References `scripts/export_model_onnx.py` for cache key hashing. (The stale `export_clip_onnx.py` reference was fixed during the export pipeline simplification.)
- `.github/workflows/ci.yml` — Runs `uv sync --extra dev` for all jobs.
- Both workflows must continue to work unchanged for CPU builds.

### Dependencies (pyproject.toml)
- `onnxruntime>=1.16.0,<2.0` is in core `[project.dependencies]` (line 14)
- `[project.optional-dependencies].dev` (lines 30-42) has pytest, torch, transformers, etc.
- `[dependency-groups].dev` (lines 129-136) has ipywidgets, onnx, onnxscript — these are DIFFERENT from the optional deps above
- `[tool.uv.sources]` pins torch to CPU-only PyTorch index
- `[tool.uv.index]` defines the pytorch-cpu index

---

## 3. Implementation Plan

### Step 1: Provider resolution module

**Create `backend/app/services/ort_providers.py`** with four functions:

1. `resolve_providers(preference: str = "auto") -> list[str]`
   - `"auto"`: probe `ort.get_available_providers()`, return best available (CUDA > DirectML > CoreML > CPU) plus CPU fallback
   - `"cpu"`: return `["CPUExecutionProvider"]`
   - `"cuda"` / `"directml"` / `"coreml"`: return requested + CPU fallback, log WARNING if unavailable
   - Catch `ImportError` for missing onnxruntime and raise a clear message

2. `get_session_options(providers: list[str]) -> ort.SessionOptions`
   - CPU: `intra_op=2, inter_op=1` (current production values)
   - CUDA: `intra_op=4, inter_op=2`
   - DirectML: `intra_op=1, inter_op=1` (dispatches async to GPU; extra threads wasteful)
   - CoreML: `intra_op=1, inter_op=1`
   - All: `ORT_ENABLE_ALL` graph optimization

3. `create_session_with_fallback(model_path, providers, sess_opts) -> tuple[ort.InferenceSession, list[str]]`
   - Try `InferenceSession(model_path, sess_opts, providers=providers)`
   - On ANY exception: log warning with exception details, recreate with `["CPUExecutionProvider"]` and CPU session options
   - Return (session, actual_providers_used)

4. `is_gpu_provider(providers: list[str]) -> bool`
   - True if first provider is not `CPUExecutionProvider`

Log provider selection at INFO level.

### Step 2: Config update

**Modify `backend/app/config.py`:**
- Remove `clip_device: str = "cpu"` (line 51)
- Add `inference_device: str = "auto"` — env var `INFERENCE_DEVICE`
- Add startup migration check: if `os.environ.get("CLIP_DEVICE")`, log a WARNING telling the user to switch to `INFERENCE_DEVICE`

### Step 3: Integrate into CLIPService

**Modify `backend/app/services/clip_service.py`** (lines 214-220):

Replace:
```python
sess_opts = ort.SessionOptions()
sess_opts.intra_op_num_threads = 2
sess_opts.inter_op_num_threads = 1
sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
providers = ["CPUExecutionProvider"]
```

With calls to:
```python
from backend.app.services.ort_providers import resolve_providers, get_session_options, create_session_with_fallback, is_gpu_provider

providers = resolve_providers(settings.inference_device)
sess_opts = get_session_options(providers)
```

Then replace the two `ort.InferenceSession(...)` calls (lines 225-230) with `create_session_with_fallback(...)`.

Store the actual providers from the **vision** session as `self._active_providers`. If vision succeeds on GPU but text falls back to CPU, treat as mixed — store CPU as the active provider for safety.

Add a read-only property:
```python
@property
def active_providers(self) -> list[str]:
    return self._active_providers
```

**DO NOT add inference-time fallback.** The singleton is shared across threads with no lock protecting session replacement. Re-creating sessions during concurrent requests is a race condition.

### Step 4: Dev scripts (ONNX + torch GPU)

**Modify `scripts/quantisation/utils.py`** (line 72-86):
- Add `device: str = "cpu"` parameter to `create_ort_session()`
- Implement provider resolution **inline** — do NOT import from `backend.app.services.ort_providers`. These scripts must remain runnable without the full backend installed. The logic is simple: map device → provider list, probe `ort.get_available_providers()`, filter to available.
- Add `get_torch_device(device: str) -> str`: returns `"cuda"` for `--device cuda`, `"cpu"` for everything else (torch doesn't support DirectML)

**Modify `scripts/quantisation/ablation_clip.py` and `ablation_siglip2.py`:**
- Add `--device` CLI argument (default `"cpu"`)
- Pass to `create_ort_session()` for ONNX
- Move torch model: `model.to(get_torch_device(args.device))`
- Move torch inputs: `inputs = processor(..., return_tensors="pt").to(get_torch_device(args.device))`

**Modify `scripts/export_model_onnx.py`:**
- Add `--device` CLI argument
- Move torch model to device during sanity check (in `torch.no_grad()` blocks)
- ONNX export MUST stay on CPU (`torch.onnx.export` requires CPU tensors)
- The `evaluate_quality()` function (gated behind `--image-dir`) loads a torch reference model — move it to device too
- Return embeddings as numpy (`.cpu().numpy()` if on CUDA)

### Step 5: Batch size adaptation

**Modify `backend/pipeline/tasks/embedding_generation.py`** (lines 46-49):

When `batch_size is None`:
```python
from backend.app.services.ort_providers import is_gpu_provider
clip_service = get_clip_service()
if is_gpu_provider(clip_service.active_providers) and clip_service.active_providers[0] == "CUDAExecutionProvider":
    batch_size = 32
else:
    batch_size = PipelineConfig().ingestion_batch_size  # default 16
```

Only CUDA gets 32. DirectML stays at 16 (integrated GPUs have limited VRAM).

### Step 6: Dependencies (pyproject.toml)

Move `onnxruntime` from core deps to conflict-marked optional extras:

```toml
# Remove from [project.dependencies]:
#   "onnxruntime>=1.16.0,<2.0",

# Add to [tool.uv]:
[tool.uv]
conflicts = [
    [
        { extra = "cpu" },
        { extra = "gpu-cuda" },
        { extra = "gpu-directml" },
    ],
]

# Add new extras and update dev extra:
[project.optional-dependencies]
cpu = ["onnxruntime>=1.16.0,<2.0"]
gpu-cuda = ["onnxruntime-gpu>=1.16.0,<2.0"]
gpu-directml = ["onnxruntime-directml>=1.16.0,<2.0"]
dev = [
    "scene-atlas[cpu]",   # Default ONNX runtime for dev
    "ruff>=0.1.0",
    "pytest>=7.4.0",
    # ... keep all existing dev deps ...
]
```

After editing, run `uv lock` to regenerate the lockfile with all three variants resolved independently.

Verify: `uv sync --extra dev` must still install onnxruntime (CPU).

### Step 7: Tests

**Create `backend/tests/unit/test_ort_providers.py`:**
- Test `resolve_providers("cpu")` returns `["CPUExecutionProvider"]`
- Test `resolve_providers("auto")` with mocked `get_available_providers()` returning various combos
- Test `resolve_providers("cuda")` when CUDA not available → falls back with warning
- Test `create_session_with_fallback` when `InferenceSession` raises → retries with CPU
- Test `get_session_options` returns correct thread counts per provider
- Test `is_gpu_provider` for various provider lists
- Mock `ort.get_available_providers()` in all tests — no real GPU needed

**Update existing tests** that mock `onnxruntime.InferenceSession` to account for the new `create_session_with_fallback` call path.

### Step 8: Electron GPU build (Windows DirectML)

**Modify `backend/pyinstaller/scene_atlas_backend.spec`:**
- Read `GPU_VARIANT = os.environ.get('GPU_VARIANT', '')`
- When `GPU_VARIANT == 'directml'`:
  - Skip `.dist-info` stripping for onnxruntime entries (change `_keep_entry` logic)
  - Add to `upx_exclude`: `'DirectML.dll'`, `'onnxruntime_providers_dml.dll'`
- When empty: keep current behaviour

**Modify `.github/workflows/electron-build.yml`:**
- (Stale `export_clip_onnx.py` reference already fixed — now uses `export_model_onnx.py`.)
- Add GPU matrix entry:
  ```yaml
  - os: windows-latest
    platform: windows
    arch: x64
    gpu: directml
  ```
- Conditional dependency install:
  ```yaml
  - name: Install Python dependencies (GPU)
    if: matrix.gpu == 'directml'
    run: uv sync --extra dev --extra gpu-directml
  - name: Install Python dependencies (CPU)
    if: matrix.gpu != 'directml'
    run: uv sync --extra dev
  ```
- Set `GPU_VARIANT=directml` env var for the sidecar build step
- Separate artifact name: `scene-atlas-windows-x64-gpu`

**Modify `electron-builder.yml`:**
- CI workflow must set `channel: gpu` for GPU builds (via env var substitution or generating the file dynamically)
- Default: `channel: latest`

**Modify `electron/src/main.ts`:**
- Read a build-time constant (e.g., injected via define plugin or environment) for the update channel
- Set `autoUpdater.channel = 'gpu'` when the GPU build is running
- Without this, GPU users will auto-update to the CPU build

**Modify `scripts/build_sidecar.py`:**
- Pass `GPU_VARIANT` through to PyInstaller invocation
- When `GPU_VARIANT=directml`: validate that `ort.get_available_providers()` includes `DmlExecutionProvider`

### Step 9: DirectML validation script

**Create `scripts/validate_directml.py`:**
- Load FP16 vision and text models with `DmlExecutionProvider`
- Set `sess_opts.log_severity_level = 0` (verbose logging)
- Run a single inference pass on a sample image and text query
- Parse ORT logs for "fallback to CPU" warnings
- Measure throughput: time N iterations on DirectML vs CPU
- Report: which ops run on GPU vs CPU, speedup ratio, any warnings
- This is a manual acceptance gate, NOT run in CI

### Step 10: Documentation and cleanup

**Create `design/gpu-acceleration.md` (ADR):**
- Architecture decision and rationale
- Installation: `uv sync --extra gpu-cuda` or `--extra gpu-directml`
- `INFERENCE_DEVICE` env var documentation
- **Prominent warning:** `auto` default can select a misconfigured GPU on servers. Recommend explicit `INFERENCE_DEVICE=cuda` or `cpu` for production.
- DirectML FP16 validation results
- Auto-update channel system
- Session options and batch size rationale

**Update docs referencing `clip_device`:**
- `.env.example` → replace `CLIP_DEVICE` with `INFERENCE_DEVICE`
- `design/decisions.md` → update reference
- `design/backend.md` → update config table
- `README.md` → update configuration section

---

## 4. Critical Pitfalls (from code review)

These were discovered during adversarial review. Violating any of these will cause bugs:

### DO NOT add inference-time fallback
The `CLIPService` singleton has `_clip_ready` set after construction, before any inference. There is no lock protecting `_vision_session` / `_text_session`. If you try to replace sessions while concurrent requests are using them, you get a race condition. The GIL doesn't help — it's released during C extension calls (`ort.InferenceSession.run()`). Session-creation fallback is sufficient.

### DO NOT import `ort_providers` from scripts
`scripts/quantisation/utils.py` currently imports nothing from `backend.app`. Adding `from backend.app.services.ort_providers import ...` creates coupling. These scripts should be runnable on a machine with just models + onnxruntime. Duplicate the ~15 lines of provider resolution logic inline.

### DO NOT use `uv pip` for package swapping in CI
`uv pip` operations bypass the lockfile. Any subsequent `uv sync` or `uv run` may re-sync and revert changes. Use uv conflict markers + `--extra gpu-directml` instead.

### Mixed provider state
`create_session_with_fallback` is called independently for vision and text sessions. Vision could succeed on GPU while text falls back to CPU. When storing `_active_providers`, use the **most conservative** result — if either session fell back, treat as CPU for batch size decisions.

### Thread counts matter per provider
DirectML and CoreML dispatch async to GPU. Setting `intra_op_num_threads=4` wastes threads and risks contention with uvicorn's thread pool. Use 1/1 for these providers, not the CUDA values of 4/2.

### `strip=True` can corrupt DLLs
The PyInstaller spec strips debug symbols. `DirectML.dll` and `onnxruntime_providers_dml.dll` may be corrupted. Add them to `upx_exclude` and test.

### Batch size 32 is dangerous for DirectML
DirectML targets "any DX12 GPU" including Intel integrated graphics with 1-2GB VRAM. Keep batch=16 for DirectML. Only CUDA gets 32.

### CI references (resolved)
The stale `scripts/export_clip_onnx.py` reference in `electron-build.yml` has been fixed — it now references `scripts/export_model_onnx.py`.

---

## 5. Files to Modify

| File | Change |
|------|--------|
| `backend/app/services/ort_providers.py` | **NEW** — provider resolution with session-creation fallback |
| `backend/app/config.py` | Remove `clip_device`, add `inference_device`, migration warning |
| `backend/app/services/clip_service.py` | Use resolver + fallback, expose `active_providers` property |
| `scripts/quantisation/utils.py` | Add device parameter, inline provider resolution |
| `scripts/quantisation/ablation_clip.py` | Add `--device` CLI arg, torch model to device |
| `scripts/quantisation/ablation_siglip2.py` | Add `--device` CLI arg, torch model to device |
| `scripts/export_model_onnx.py` | Add `--device` for sanity check and evaluation torch inference |
| `backend/pipeline/tasks/embedding_generation.py` | Provider-aware batch size |
| `pyproject.toml` | Conflict markers, move onnxruntime to optional extras |
| `backend/tests/unit/test_ort_providers.py` | **NEW** — unit tests |
| `backend/pyinstaller/scene_atlas_backend.spec` | `.dist-info` + `upx_exclude` for GPU builds |
| `scripts/build_sidecar.py` | Pass `GPU_VARIANT`, validate package |
| `.github/workflows/electron-build.yml` | Fix stale ref, add GPU matrix entry |
| `electron-builder.yml` | Update channel support |
| `electron/src/main.ts` | Set `autoUpdater.channel` from build variant |
| `scripts/validate_directml.py` | **NEW** — FP16 compatibility validation |
| `design/gpu-acceleration.md` | **NEW** — ADR |
| `.env.example` | Replace `CLIP_DEVICE` → `INFERENCE_DEVICE` |
| `design/decisions.md` | Update `clip_device` reference |
| `design/backend.md` | Update config table |
| `README.md` | Update configuration section |

---

## 6. Verification Checklist

1. **CPU default:** `uv sync --extra dev && uv run pytest` — all existing tests pass
2. **Provider resolution tests:** New unit tests pass with mocked providers
3. **GPU smoke test (if available):** `INFERENCE_DEVICE=cuda uv run python scripts/start.py` → logs show CUDA selected → search and ingest work
4. **DirectML validation:** `scripts/validate_directml.py` on Windows DX12 GPU → no op fallback warnings, measurable speedup
5. **Ablation GPU:** `uv run python -m scripts.quantisation.ablation_clip --device cuda` → runs, same quality metrics
6. **Electron CPU build:** `GPU_VARIANT` unset → starts with CPUExecutionProvider
7. **Electron GPU build:** `uv sync --extra dev --extra gpu-directml && GPU_VARIANT=directml` → DmlExecutionProvider selected
8. **Auto-update:** CPU writes `latest.yml`, GPU writes `latest-gpu.yml`, no cross-update
9. **macOS CoreML:** Auto-detection works or falls back silently with INFO log
10. **Migration:** `CLIP_DEVICE=cuda` in `.env` → deprecation warning in logs

---

## 7. Suggested Implementation Order

The steps have dependencies. Recommended order:

1. **Step 6 (pyproject.toml)** — Do this first. Run `uv lock` and verify `uv sync --extra dev` still works. This validates the conflict markers approach before touching any code.
2. **Step 1 (ort_providers.py)** — New file, no dependencies on other changes.
3. **Step 7 (tests)** — Write tests for the new module immediately.
4. **Step 2 (config.py)** — Small change, quick to verify.
5. **Step 3 (clip_service.py)** — Core integration. Run existing tests after.
6. **Step 5 (batch size)** — Depends on Step 3 (needs `active_providers`).
7. **Step 4 (dev scripts)** — Independent of backend changes. Can be done in parallel with Steps 3-5.
8. **Step 8 (Electron GPU build)** — Depends on Steps 1-6 being complete and tested.
9. **Step 9 (validation script)** — Can be done any time, but most useful after Step 8.
10. **Step 10 (docs)** — Last, after everything is working.
