# Split Storage, WebP Conversion & Setup Wizard

**Date:** 2026-03-15
**Status:** Approved

## Overview

Three related changes that improve the first-run experience and long-term storage efficiency:

1. **Split storage paths** — separate fast app-data (DB, index, thumbnails) from cold image storage (originals, backups).
2. **WebP conversion** — optional lossless conversion of imported images and their thumbnails to WebP on ingest.
3. **Setup wizard update** — first-run wizard collects both paths and the WebP preference; Settings UI exposes all three.

---

## 1. Backend: Config Split

### Approach

Replace the single `DATA_DIR` / `data_dir` with two independent roots. The `Settings` class in `backend/app/config.py` currently derives all paths from `data_dir`; the `__init__` method recomputes derived paths when `data_dir` is overridden. The same pattern is extended for two roots.

### New environment variables

| Env var | Default | Purpose |
|---------|---------|---------|
| `APP_DATA_DIR` | `{base_dir}/data` | Fast-access files (DB, LanceDB, thumbnails, staging, logs) |
| `IMAGE_LIBRARY_DIR` | `{base_dir}/images` | Cold-storage files (originals, backups) |
| `DATA_DIR` | *(removed)* | No longer used |

### Derived path mapping

| Path | Root | Notes |
|------|------|-------|
| `battlemap.db` | `APP_DATA_DIR` | — |
| `lancedb/` | `APP_DATA_DIR` | — |
| `store/thumbnails/` | `APP_DATA_DIR` | — |
| `staging/` | `APP_DATA_DIR` | — |
| `config/` | `APP_DATA_DIR` | Moved from `base_dir/config` |
| *(images)* | `IMAGE_LIBRARY_DIR` | Hash-sharded directly under the root — no `store/images/` nesting |
| `backups/` | `IMAGE_LIBRARY_DIR` | Large SQLite + LanceDB snapshots belong on cold storage |

The image store flattens: `{IMAGE_LIBRARY_DIR}/a1/b2/a1b2c3d4e5f6.jpg` instead of `{DATA_DIR}/store/images/a1/b2/…`.

### Settings class changes

```python
# Remove
data_dir: Path
store_images_dir: Path
store_thumbnails_dir: Path
staging_dir: Path
vector_db_path: Path
database_url: str  # (now a computed property)

# Add
app_data_dir: Path = base_dir / "data"
image_library_dir: Path = base_dir / "images"

# Computed from app_data_dir
store_thumbnails_dir: Path  # = app_data_dir / "store" / "thumbnails"
staging_dir: Path           # = app_data_dir / "staging"
vector_db_path: Path        # = app_data_dir / "lancedb"
config_dir: Path            # = app_data_dir / "config"

# Computed from image_library_dir
store_images_dir: Path      # = image_library_dir (flat root)
backups_dir: Path           # = image_library_dir / "backups"

@property
def database_url(self) -> str:
    return f"sqlite:///{self.app_data_dir / 'battlemap.db'}"
```

The `__init__` override pattern is preserved: if `app_data_dir` or `image_library_dir` are overridden via env, recompute all dependents accordingly.

### Startup validation

On startup, if either configured root directory does not exist, the backend **logs a clear error and raises** rather than silently creating an unexpected directory tree. The Electron main process surfaces this as a user-visible error dialog (see Section 3).

Directory creation still runs for expected **subdirectories** within configured roots (thumbnails, staging, lancedb, config) — but not for the roots themselves. The roots are created by Electron's `setup:complete` handler (new installs) or are pre-existing (existing installs and server mode). In server mode, operators are expected to create and configure the roots before starting the backend.

---

## 2. WebP Conversion in the Pipeline

### App settings

Three new keys in the `app_settings` table (added via `seed_default_settings()`):

| Key | Default | Type | Notes |
|-----|---------|------|-------|
| `convert_to_webp` | `true` | `bool` | Master switch |
| `webp_lossless` | `true` | `bool` | `True` = lossless (recommended); `False` = quality-based lossy |
| `webp_quality` | `95` | `int` | Used only when `webp_lossless = False` |

The Settings UI exposes only the master switch (`convert_to_webp`). The `webp_lossless`/`webp_quality` keys are operator-level tuning via direct DB edit for now.

### Conversion in `prepare_single_image`

Conversion is inserted in the **normal (non-duplicate) path**, after the staged file is identified but **before** `image_store.put()`. This ensures:
- `file_size` reflects the stored (WebP) file.
- The `storage_key` extension is `.webp`.
- The SHA-256 hash is computed from the **post-conversion** file, so dedup matches on stored content.

**Pre-computed hash invalidation:** The web import path sends a `content_hash` in `metadata` (pre-computed from the staged file by the frontend, before conversion). When conversion occurs, this pre-computed hash is **discarded** and recomputed from the converted file. Implementation: after converting, set `content_hash = None` so the existing `if not content_hash: content_hash = _compute_file_hash(...)` branch re-runs on the WebP file.

**Skip conditions** (conversion has no effect when):
- File is a video.
- File is already WebP.
- File is an animated GIF (`n_frames > 1` via Pillow).

**Mode handling** (Pillow):
- Palette (`P`) with transparency → `RGBA`
- Palette (`P`) without transparency → `RGB`
- `CMYK` → `RGB`
- `RGBA`, `LA` → keep as-is (preserve transparency)
- Everything else → `RGB`

**Conversion procedure:**
1. Open staged file with Pillow.
2. Check skip conditions; skip if any apply.
3. Convert mode as above.
4. Save to `{staged_path.stem}.webp` in the same staging directory with `lossless=True, method=4` (`method=4` balances encode speed and compression ratio; see Pillow WebP docs).
5. Delete the original staged file.
6. Update `image_path_obj` to the new `.webp` path.
7. Set `ext = '.webp'`, regenerate `storage_key` with `.webp` extension.
8. Set `content_hash = None` (discard pre-computed hash; will recompute below).
9. Proceed — hash, copy to store, thumbnails all operate on the WebP file.

### Thumbnails

`generate_thumbnails` in `backend/pipeline/tasks/image_processing.py` currently saves all sizes as JPEG. When `use_webp=True`:
- Save thumbnails as WebP instead of JPEG.
- Keys become `{stem}_400x400.webp` (not `.jpg`).
- `save(..., format='WEBP', lossless=False, quality=90)` — thumbnails are small and served at screen resolution; quality-based is fine here.

`generate_thumbnails` receives a `use_webp: bool` argument. `PipelineConfig` gains a `use_webp: bool` field populated from `app_settings` at pipeline startup. `prepare_single_image` passes `pipeline_config.use_webp` through to `_gen_thumbs`.

### Stored format reflected in DB

When conversion occurs:
- `storage_key` ends in `.webp` — the format is inferred from this at read time.
- `original_filename` (the `filename` column) retains the human-readable pre-conversion name (e.g., `map_winter.png`) — display only, never used for file access.

There is no separate `file_extension` DB column. The `storage_key` is the authoritative reference to the stored file and its format.

### What does NOT change

- Thumbnail generation for videos (first-frame extraction is still JPEG; the frame is discarded after use).
- Existing images in the library — conversion is import-time only. No backfill migration.
- DB `media_type` field — stays `"image"` for WebP (format is not type).

---

## 3. Electron Config & Setup Wizard

### Config file schema

Current: `{ dataDir: string }`
Updated: `{ appDataDir: string, imageLibraryDir: string, convertToWebp: boolean }`

Old `dataDir` key is retained in the config file for migration detection (see Section 4).

### Setup wizard (`electron/setup.html`)

Replaces the current single-path picker with the approved v5 mockup design (`.superpowers/brainstorm/361892-1773536017/setup-wizard-v5.html`). Three inputs:

1. **App data location** — folder picker with "SSD recommended" hint; default: `{Documents}/Scene Atlas/data`
2. **Image library location** — folder picker; default: `{Documents}/Scene Atlas/images`
3. **Convert images to WebP** — toggle, default on

On "Get Started", `setup:complete` IPC handler in `main.ts`:
1. Calls `fs.mkdirSync(appDataDir, { recursive: true })` and `fs.mkdirSync(imageLibraryDir, { recursive: true })` to create both roots before launching the backend. (The backend validates they exist; Electron creates them.)
2. Saves config with `{ appDataDir, imageLibraryDir, convertToWebp }`.
3. Closes the setup window and launches the app.

### New IPC channels

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `setup:get-default-dirs` | renderer → main | Returns `{ appDataDir, imageLibraryDir }` defaults |
| `setup:choose-directory` | renderer → main | Opens native folder picker (existing, reused) |
| `setup:complete` | renderer → main | Creates roots, saves config, closes setup, launches app |

Remove: `setup:get-default-dir` (singular) → replaced by `setup:get-default-dirs`.

### Settings IPC additions / changes

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `system:get-app-data-dir` | renderer → main | Returns current `appDataDir` |
| `system:get-image-library-dir` | renderer → main | Returns current `imageLibraryDir` |
| `system:choose-app-data-dir` | renderer → main | Opens folder picker |
| `system:choose-image-library-dir` | renderer → main | Opens folder picker |
| `system:change-storage-dirs` | renderer → main | Saves new paths; calls `app.relaunch()` + `app.exit(0)` for immediate restart |

`system:change-storage-dirs` saves the new values to config and calls `app.relaunch()` + `app.exit(0)` for an immediate restart. The deferred restart model originally described here was not implemented; the actual behaviour matches the old `system:change-data-dir` approach of relaunching immediately.

Remove: `system:get-data-dir`, `system:open-data-dir`, `system:change-data-dir`.

### Sidecar args (`electron/src/sidecar.ts`)

Remove: `--data-dir {dataDir}`
Add: `--app-data-dir {appDataDir}` `--image-library-dir {imageLibraryDir}`
Also set env var: `CONVERT_TO_WEBP={convertToWebp ? '1' : '0'}` on the sidecar process (used by `seed_default_settings` on first boot — see below).

### Backend entry point (`backend/pyinstaller/entry.py`)

Parse `--app-data-dir` and `--image-library-dir`; set `APP_DATA_DIR` and `IMAGE_LIBRARY_DIR` env vars before importing the app module.

### WebP preference flow

1. Setup wizard captures `convertToWebp` → saved in Electron config.
2. `sidecar.ts` passes `CONVERT_TO_WEBP` env var (`'1'` or `'0'`) to the sidecar process.
3. On first backend start, `seed_default_settings()` checks `os.environ.get('CONVERT_TO_WEBP')` before inserting the `convert_to_webp` default: if the env var is present, use it; otherwise use `True`. This ensures the wizard choice wins on the first run.
4. In server mode (no Electron), the default is `True` unless `CONVERT_TO_WEBP=0` is set in the environment.
5. Thereafter, `convert_to_webp` is DB-driven and editable via Settings UI without restart.

---

## 4. Migration for Existing Installations

Triggered in `electron/src/config.ts` when the loaded config has `dataDir` but not `appDataDir`/`imageLibraryDir`.

```
appDataDir      ← dataDir                  (no files move)
imageLibraryDir ← dataDir/store/images     (existing image directory becomes new library root)
```

**Why this works:** the image store already writes to `{dataDir}/store/images/` using the hash-sharded structure. After migration, `IMAGE_LIBRARY_DIR = {dataDir}/store/images`, and the existing files are at `{IMAGE_LIBRARY_DIR}/a1/b2/...` — matching the new flat-root path scheme exactly.

**Backups:** Existing backups at `{dataDir}/backups/` are **not** moved. New backups will go to `{imageLibraryDir}/backups/` = `{dataDir}/store/images/backups/`. This is a slight layout quirk for migrated installs. It is documented in the UI: a one-time info callout in Settings for migrated users notes the divergence and encourages users to reconfigure `imageLibraryDir` to a top-level path if they want a cleaner layout. Any such reconfiguration is manual (user moves files, updates setting).

After migration: write `{ appDataDir, imageLibraryDir, convertToWebp: true }` to config, remove `dataDir` key.

---

## 5. Settings UI Changes

### General tab — Storage Locations section

Added as the **first section** in the General tab, above existing General settings, using the `SettingRow` component:

```
STORAGE LOCATIONS
─────────────────────────────────────────────────────────
App data location     [/path/to/data              ] [Browse]
                      Database, thumbnails & search index.
                      SSD recommended. Needs ~2 GB free by
                      default.                    ⚠ Restart required

Image library location  [/path/to/images            ] [Browse]
                        Original images and backups. Any drive
                        including external storage. ⚠ Restart required
```

Both rows carry `RestartBadge`. When either path is changed via Browse, an inline warning appears below the row:

> "Changing this path does not move your files. You must move them manually before restarting."

A "Restart Now" button appears once the user has changed at least one path. No additional confirmation step is needed — the Browse action itself constitutes confirmation. This matches the `system:change-storage-dirs` deferred-restart model.

### Import tab — existing Import section

The **WebP toggle is placed in the Import tab** alongside other import-processing settings (grid detection, limits):

```
Convert imports to WebP    [toggle — on by default]
                           Reduces file size 20–40% with no quality
                           loss. Applies to new imports only.
```

No `RestartBadge` — `convert_to_webp` is read per-import job from the DB and takes effect immediately on the next import.

---

## Testing Considerations

- Unit tests for `Settings` init: derived paths computed correctly from both roots independently; direct env var override correctly recomputes dependents.
- Unit tests for startup validation: missing root raises with a clear message; existing root does not raise; subdirectories are created if missing.
- Unit tests for WebP conversion helper: mode conversions (P→RGBA, P→RGB, CMYK→RGB, RGBA passthrough); animated GIF skip; already-WebP skip; video skip; pre-computed hash is discarded and recomputed after conversion.
- Unit tests for `generate_thumbnails`: `.webp` keys when `use_webp=True`; `.jpg` keys when `False`.
- Integration test: full import pipeline with `convert_to_webp=True`; assert stored file is WebP, thumbnail keys end in `.webp`, `storage_key` ends in `.webp`, `original_filename` retains original extension.
- Integration test: full import pipeline with pre-computed `content_hash` in metadata and `convert_to_webp=True`; assert hash in DB matches the stored WebP file, not the original.
- Electron config migration unit test: `{ dataDir: '/foo' }` → `{ appDataDir: '/foo', imageLibraryDir: '/foo/store/images', convertToWebp: true }`.

---

## Files to Change

| File | Change |
|------|--------|
| `backend/app/config.py` | Replace `data_dir` with `app_data_dir` + `image_library_dir`; recompute all derived paths; startup validation |
| `backend/pipeline/prepare.py` | Insert WebP conversion before `image_store.put()`; discard pre-computed hash after conversion; recompute hash from WebP |
| `backend/pipeline/tasks/image_processing.py` | Add `use_webp: bool` param to `generate_thumbnails`; save as WebP when enabled |
| `backend/pipeline/pipeline_config.py` | Add `use_webp: bool` field |
| `backend/app/services/settings_service.py` | Seed `convert_to_webp`, `webp_lossless`, `webp_quality` defaults; honour `CONVERT_TO_WEBP` env var in seeding |
| `electron/src/config.ts` | New schema with two roots; migration from `dataDir`; default paths for both roots |
| `electron/src/main.ts` | New IPC handlers; `mkdirSync` for both roots on `setup:complete`; deferred-restart for storage path changes |
| `electron/src/sidecar.ts` | Pass `--app-data-dir`, `--image-library-dir` args; set `CONVERT_TO_WEBP` env var |
| `electron/src/preload.ts` | Expose new storage IPC methods; remove old `changeDataDir`/`getDataDir` |
| `electron/src/setup.preload.ts` | Update `setupAPI` for `get-default-dirs` and three-value `setup:complete` |
| `electron/setup.html` | Full replacement with v5 design |
| `backend/pyinstaller/entry.py` | Parse `--app-data-dir`, `--image-library-dir` CLI args |
| `frontend/src/components/settings/GeneralSettings.tsx` | Add Storage Locations section (first section in General tab) |
| `frontend/src/components/settings/ImportSettings.tsx` | Add WebP conversion toggle to Import tab |
| `frontend/src/hooks/useElectron.ts` (or equivalent) | Expose new storage IPC calls; remove old data-dir calls |
| `design/storage.md` | Update path table, note new roots, update backup location |
| `design/electron.md` | Update IPC table, config schema, startup sequence |
