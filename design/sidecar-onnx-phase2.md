# Sidecar Size Reduction — Phase 2: ONNX Runtime

> **Note:** This plan has been fully implemented as ADR-014. This document is retained as a historical reference only.

## Status: Implemented (ADR-014)

Phase 1 (CPU-only torch + opencv-headless + spec exclusions) reduced the sidecar from
7.2 GB to approximately 450–550 MB. Phase 2 targets a further reduction by replacing
`torch` and `transformers` at **runtime** with `onnxruntime`, which is ~30 MB vs ~260 MB.

## Motivation

After Phase 1 the sidecar still ships `libtorch_cpu.so` (~180 MB) and the full `transformers`
data tree (~57 MB). The service only uses two model classes: `CLIPModel` and `CLIPProcessor`.
Replacing the inference path with ONNX Runtime removes both libraries from the frozen bundle.

## Target Size

| Scenario | Sidecar | First-run download | Notes |
|---|---|---|---|
| Phase 1 (current) | ~500 MB | ~340 MB HF model | Model cached in `~/.cache/huggingface/` |
| Phase 2A — bundled | ~620 MB | 0 | Offline after install; ONNX baked into sidecar |
| Phase 2B — HF hosted | ~240 MB | ~380 MB ONNX files | Smallest sidecar; requires hosting ONNX files |

Phase 2B (hosted) has the same total first-run footprint as Phase 2A but smaller download
size for each release. It requires a one-time upload to HuggingFace Hub (free).

## Architecture

### ONNX Export (build-time, dev environment only)

A new script `scripts/export_clip_onnx.py` runs with the dev venv (which has `torch`) and
exports two ONNX graphs from the cached HuggingFace model:

```
clip_vision_encoder.onnx
  Input:  pixel_values  [batch, 3, 224, 224]  float32
  Output: embeddings    [batch, 512]           float32  (L2-normalised)

clip_text_encoder.onnx
  Input:  input_ids       [batch, 77]  int64
          attention_mask  [batch, 77]  int64
  Output: embeddings      [batch, 512] float32  (L2-normalised)
```

The projection heads and L2 normalisation are baked into the exported graphs so that
`clip_service.py` can call `.run()` and get the final embeddings directly.

The tokenizer vocab files (`tokenizer.json`, `merges.txt`, `special_tokens_map.json`,
`tokenizer_config.json`) are copied alongside the ONNX files from the HF cache.

### Runtime Inference (`backend/app/services/clip_service.py`)

Replace:
- `CLIPModel` → `onnxruntime.InferenceSession`
- `CLIPProcessor` image path → PIL + numpy (resize shortest side to 224, centre-crop, normalise
  with CLIP mean/std)
- `CLIPProcessor` text path → `tokenizers.Tokenizer` loaded from the bundled `tokenizer.json`
  (the `tokenizers` library is already a dependency via `transformers`)

The public interface of `CLIPService` is unchanged: `encode_image`, `encode_text`,
`batch_encode_images` all return `list[float]`.

### Dependency Changes

```toml
# pyproject.toml — production
dependencies = [
  ...
  "onnxruntime>=1.16.0,<2.0",   # replaces torch at runtime
  # torch and transformers removed from production deps
]

[project.optional-dependencies]
dev = [
  ...
  "torch>=2.1.0,<3.0",          # needed for ONNX export only
  "transformers>=4.36.0,<5.0",  # needed for ONNX export only
]
```

### PyInstaller Spec Changes

- Remove `collect_all('torch')` / `collect_all('transformers')` entirely
- Add `onnxruntime` to `hiddenimports`
- Add ONNX files and tokenizer vocab as `datas`
- For Phase 2A (bundled): include `backend/models/*.onnx` and vocab files directly
- For Phase 2B (hosted): include just the tokenizer vocab; ONNX downloaded at runtime
  via `huggingface_hub.snapshot_download`

### ONNX Model Hosting (Phase 2B only)

1. Run `scripts/export_clip_onnx.py` → generates files in `backend/models/` (gitignored)
2. Create a HuggingFace Hub repo, e.g. `<org>/scene-atlas-clip-onnx`
3. Upload with `huggingface_hub.upload_folder()`
4. On first run in the sidecar, `clip_service.py` calls
   `snapshot_download("scene-atlas/clip-onnx", local_dir=data_dir/"clip_onnx")` and loads
   from there; subsequent runs use the cached directory

## Files to Create/Modify

| File | Change |
|------|--------|
| `scripts/export_clip_onnx.py` | New: ONNX export script, run once in dev env |
| `backend/app/services/clip_service.py` | Replace torch+transformers with onnxruntime |
| `pyproject.toml` | Move torch+transformers to dev deps; add onnxruntime prod dep |
| `backend/pyinstaller/scene_atlas_backend.spec` | Remove torch/transformers collection; add onnxruntime + model files |
| `scripts/build_sidecar.py` | Add pre-flight: check ONNX files exist, else abort with instructions |

## Verification

1. `uv run python scripts/export_clip_onnx.py` — exports and saves ONNX + vocab to
   `backend/models/`
2. Sanity check embeddings: encode the same image/text via both the old torch path and the
   new ONNX path; cosine similarity should be > 0.999
3. `uv run python scripts/build_sidecar.py --clean`
4. `du -sh backend/pyinstaller/dist/scene-atlas-backend/` — confirm target size
5. `uv run pytest` — full test suite must pass
6. End-to-end: run sidecar, upload an image, run a text search — results must match the
   torch baseline

## Risks

- **ONNX export graph correctness**: The exported graph must include the projection head and
  normalisation. Validate output numerically against the torch baseline before shipping.
- **Tokenizer compatibility**: The `tokenizers` library BPE implementation must produce
  identical token IDs to `transformers.CLIPTokenizer`. Test with a representative set of
  queries.
- **onnxruntime thread count**: By default onnxruntime may spawn many threads. May need
  `sess_options.intra_op_num_threads = 2` to avoid contention with uvicorn workers.
- **Windows path**: The deferred-import pattern in `clip_service.py` (avoiding Windows
  directory scan at import time) should be preserved for onnxruntime too.
