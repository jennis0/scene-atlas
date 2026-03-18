# HuggingFace Model Management

**Date:** 2026-03-15
**Status:** Implemented

## Overview

Scene Atlas ships without bundled ONNX models. On first boot the user selects an
embedding model, which is downloaded from HuggingFace and stored in `APP_DATA_DIR/models/`.
The active model is persisted to the database and can be changed at any time; switching
triggers a background job that reloads both the CLIP service and the LanceDB table,
then re-embeds all scenes.

Three model sizes are offered, each exported as a pair of ONNX files (vision + text
encoder) and hosted in a dedicated HF repo under the `jennis0` namespace.

---

## Model Registry

`backend/app/services/model_registry.py` is the single source of truth for model
metadata. It is used at runtime (download, selection, API responses) and by the export
and publish scripts.

| Name   | HF repo                        | Architecture                    | Size  | Recommended for |
|--------|--------------------------------|---------------------------------|-------|-----------------|
| small  | jennis0/scene-atlas-small      | CLIP ViT-B/32, vision fp16, text int8  | ~250 MB | CPU-only machines |
| medium | jennis0/scene-atlas-medium     | SigLIP2-base-patch16-224, vision fp16, text int8 | ~500 MB | Any hardware (default with GPU) |
| large  | jennis0/scene-atlas-large      | SigLIP2-so400m-patch14-384, vision fp16/fp16 | ~1 GB   | GPU strongly recommended |

`get_default_model(has_gpu)` returns `"medium"` when a GPU is detected, otherwise
`"small"`. The large model is not auto-recommended; it must be selected explicitly.

Both ONNX files use fixed filenames (`clip_vision_encoder.onnx`,
`clip_text_encoder.onnx`) across all models. `manifest.json` is the HF-side metadata
file written by the publish script.

---

## Model Resolution

`_get_active_model_name()` in `clip_service.py` resolves the active model name via a
three-step priority chain:

1. **`EMBEDDING_MODEL` env var** — operator override, bypasses DB entirely. Useful for
   dev environments and testing.
2. **`active_model` key in `app_settings` DB** — the normal runtime path after the user
   has chosen a model.
3. **Auto-detect** — if the DB key is absent (fresh install), calls
   `resolve_providers("auto")` and checks for GPU providers. Returns `"medium"` if a
   real GPU provider is present, `"small"` otherwise.

`active_model` is intentionally **not seeded** into the DB on first boot. The empty
string default in `AppSettings` means a missing DB row falls through to auto-detect,
which is the correct behaviour before the user has made any selection.

`get_effective_model_name()` is the public API. It returns `_active_model_name` (the
name set during the last successful service load) if the service has already loaded,
otherwise falls back to `_get_active_model_name()`. This avoids a DB hit on every API
call once the service is running.

---

## Download & Version Tracking

`backend/app/services/model_download_service.py` manages the download lifecycle.

**Storage layout:**

```
APP_DATA_DIR/
  models/
    small/
      manifest.json
      clip_vision_encoder.onnx
      clip_text_encoder.onnx
      version.json          ← completion marker
    medium/  ...
    large/   ...
    .tmp/                   ← transient; cleaned up after each download attempt
      <name>/
```

**Atomic download pattern:**

1. Fetch the HF commit SHA *before* downloading (avoids a post-download race).
2. Download via `snapshot_download()` into `.tmp/<name>/` (wiping any pre-existing temp
   dir first).
3. Verify all required files (`manifest.json`, both `.onnx` files) exist in the temp
   dir.
4. Atomic rename: `tmp_dir.rename(model_dir)` — replaces any previous installation in
   one filesystem operation.
5. Write `version.json` last as the **completion marker**.

`is_model_downloaded()` checks only for the existence of `version.json`. Any directory
without it is treated as incomplete, ensuring a crashed or interrupted download is never
used.

`version.json` stores `hf_commit_sha` and `downloaded_at`. The SHA enables future
update detection (not yet implemented — see Future Considerations).

**Error handling:** `ModelDownloadError` wraps all failure modes (network, HTTP, OS)
with user-readable messages. The API layer surfaces these as job failure details.

---

## Model Switching

`POST /api/v1/models/active` is the only way to change the active model. It:

1. Writes `active_model` directly to the DB via `db.merge(AppSetting(...))`, bypassing
   `update_settings()` / `AppSettingsPatch`. This avoids side-effects from the general
   settings update path and makes the intent explicit.
2. Submits `_download_and_activate` as a background job.

**Why `active_model` is not in `AppSettingsPatch`:** Switching the active model is not a
simple key-value update — it triggers a multi-step background job (download, service
reload, re-embed). Routing it through the general settings patch would obscure that
intent, require special-casing, and risk the job being skipped if settings are patched
without going through the models API.

**`_download_and_activate` job sequence:**

1. Download the model (skipped if already downloaded).
2. `reload_clip_service()` — clears the singleton, resets `_clip_ready`, starts a
   background load thread.
3. `wait_for_clip_ready()` — blocks the job thread until the new model is loaded (or
   fails). Safe to call from any thread.
4. `reload_lancedb_service(f"embeddings_{name}")` — closes the old LanceDBService (freeing
   file handles) and replaces the singleton with one pointed at the new table.
5. `rebuild_all_embeddings(force=True)` — re-embeds all scenes using the new model.
   `force=True` is required because the embeddings pipeline normally skips scenes that
   already have embeddings; after a model switch the existing embeddings are for the old
   model and must be regenerated.

If the job fails at any step, `active_model` in the DB already points to the new model
name. The service will be in a degraded state until the user retries via
`POST /api/v1/models/active`.

---

## LanceDB Tables

Each model has its own LanceDB table named `embeddings_{model_name}` (e.g.
`embeddings_small`, `embeddings_medium`). This means stale embeddings from a previous
model are preserved rather than deleted on switch — the user can inspect and clean them
up explicitly.

`LanceDBService.delete_table_by_name()` refuses to delete the currently active
table (raises `ValueError`). The API layer enforces the same guard, returning HTTP
409 if the caller tries to delete embeddings for the active model. The user must switch
to a different model first.

`reload_lancedb_service(table_name)` holds `_init_lock` during the swap to prevent
races, closes the old service to avoid file-handle leaks, then replaces the global
singleton.

---

## GPU Detection

`resolve_providers("auto")` (in `ort_providers.py`) returns the ORT provider list for
the current hardware. `GPU_PROVIDERS` in `model_registry.py` is the authoritative set of
providers that indicate real hardware acceleration:

- `CUDAExecutionProvider` (NVIDIA)
- `DmlExecutionProvider` (DirectML, Windows)
- `CoreMLExecutionProvider` (Apple Silicon)

`_has_real_gpu_provider()` checks for intersection with this set. The `"auto"` resolution
path in `_get_active_model_name()` uses this to pick the default model.

The `GET /api/v1/models/setup-status` response includes:
- `has_gpu` — whether any GPU provider was detected
- `gpu_provider` — the best available provider name (priority: CUDA > DML > CoreML),
  or `null` if CPU-only
- `recommended` — the model name `get_default_model(has_gpu)` would return

The frontend uses `gpu_provider` to show a human-readable hardware label (e.g.
"NVIDIA GPU (CUDA)") via `GPU_PROVIDER_LABELS`.

---

## API

All endpoints are under `/api/v1/models/`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all models with download status and active flag |
| `GET` | `/setup-status` | GPU detection + whether a model download is needed |
| `POST` | `/active` | Set the active model; triggers download + re-embed job |
| `POST` | `/{name}/download` | Download a model without activating it |
| `GET` | `/{name}/embeddings` | LanceDB table stats for a model's embeddings |
| `DELETE` | `/{name}/embeddings` | Delete stale embeddings for a non-active model |

`POST /active` and `POST /{name}/download` return `{ status, job_id }`. The caller
should poll `GET /api/v1/jobs/{job_id}` to track progress.

---

## First-Boot Experience

**Web / server mode:** `App.tsx` calls `GET /api/v1/models/setup-status` on mount. If
`needs_model` is true, a full-screen `ModelSetupScreen` overlay is rendered in place of
the main gallery. The overlay guides the user through model selection and download, then
calls `onComplete` to dismiss itself and render the gallery.

`needs_model` is true when no model that matches `get_effective_model_name()` is
downloaded. On a fresh install with no DB entry, this means no model is downloaded at
all.

**Electron mode:** Model selection wizard is implemented as `ModelSetupScreen.tsx` (web/server mode). Electron integration uses the Electron setup window.

---

## Deployment Modes

| Mode | Model storage | First-boot flow | Notes |
|------|--------------|-----------------|-------|
| Electron | `APP_DATA_DIR` managed by Electron | Wizard step (stub) | Wizard not yet integrated |
| Web / server | Operator-controlled `APP_DATA_DIR` | `ModelSetupScreen` overlay | `EMBEDDING_MODEL` env var can pre-select |
| Dev | `APP_DATA_DIR` or `backend/models/<name>/` fallback | Same as web | Fallback path allows testing with locally exported models |

Fallback path in `_default_models_dir()` (`clip_service.py`) checks `APP_DATA_DIR/models/<name>/` first,
then `backend/models/<name>/`. This allows developers to test with models
exported by `scripts/models/export_model_onnx.py` without a full HF download.

---

## Stale Embeddings

When the user switches from model A to model B, the `embeddings_A` LanceDB table is
left intact. This uses disk space but avoids data loss in case the user switches back.

To reclaim space the user can delete stale tables via
`DELETE /api/v1/models/{name}/embeddings`. The UI surfaces this alongside per-model
embedding stats (`GET /api/v1/models/{name}/embeddings`). The guard preventing deletion
of the active table is enforced at both the service layer and the API layer.

If the user switches back to model A, the existing `embeddings_A` table will be
reused and re-embed will regenerate all vectors into it (with `force=True`).

---

## Future Considerations

**Update detection:** `version.json` stores `hf_commit_sha` specifically to enable
future update checks — compare the stored SHA against the latest HF commit SHA for the
repo. No auto-update is currently planned; this would require a polling mechanism and a
UI affordance to trigger re-download.

**Electron wizard integration:** Model selection wizard is implemented as `ModelSetupScreen.tsx` (web/server mode). Electron integration uses the Electron setup window. When the split-storage wizard is implemented, the model step
should be merged into it as a single coherent first-run experience for Electron users.

**Large model VRAM management:** The large model's ~1 GB footprint is flagged in the
registry with `recommended_hardware: "gpu"`. ORT session memory management (especially
DirectML leak workarounds already in place for vision inference) may need revisiting if
the large model sees broad adoption.
