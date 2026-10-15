# Web Import Flow

> **Being replaced:** this describes the current import flow, which is being redesigned. See [ingest-redesign.md](ingest-redesign.md) and ADR-018.

## Overview

The web import allows users to upload images (files, folders, or zip archives) through the browser. After upload, groups are auto-confirmed and processing starts immediately. Images are immediately visible in search and the gallery after import.

For state machine details, see [import-state-machine.md](import-state-machine.md).

## User Flow

```
Gallery → [Import button] → ImportDialog opens
  → Select files or folder (or .zip)
  → Files uploaded to staging in batches (init → upload-batch ×N → analyse)
  → Backend analyses files, groups into image groups, generates preview thumbnails
  → Empty authors defaulted to "Unknown" (frontend-only default — the backend accepts null/empty author)
  → Auto-confirm all groups via POST /confirm-all (no user review step)
  → Dialog shows processing state (per-group spinners)
  → User can close dialog → ActivityDock tracks progress
  → On completion → toast notification fires ("Import complete — N groups, N images")
  → Images immediately visible in gallery
  → ActivityDock entry dismissed automatically
```

## Three-Phase Upload

Files are uploaded in batches to avoid timeouts and enable progress tracking, then analysed separately.

### Phase 1: Init

**`POST /api/v1/imports/init`**

Creates a job in `uploading` status with an empty staging directory. Returns `{ job_id }`. The frontend immediately persists this to localStorage so the job survives dialog close.

### Phase 2: Upload Batches (×N)

**`POST /api/v1/imports/{job_id}/upload-batch`**

Accepts `multipart/form-data`:
- `files`: one or more image files or .zip archives (max 20 files or 100 MB per batch)
- `relative_paths` (optional): JSON array of relative paths (from `webkitRelativePath` or zip structure)

**Processing:**
1. Validate job exists and is in `uploading` state
2. For each file:
   - If `.zip`: extract, skip `__MACOSX`/`._` files, filter to supported formats
   - Otherwise: save to staging preserving relative path structure
3. Return `BatchUploadResponse` with counts

**Response:** `{ "files_saved": 5, "bytes_saved": 10485760, "skipped_invalid": [] }`

The frontend splits files into batches (≤20 files, ≤100 MB each) and sends them sequentially. Each batch uses Axios `onUploadProgress` for byte-level progress feedback, which drives the progress bar in the UI. On network or 5xx errors, up to 2 retries are made with exponential backoff.

**On failure:** The frontend calls `POST /{job_id}/fail` with an `error_message` to mark the job as `failed` (semantically accurate — not a user cancellation). The staging TTL handles any remaining cleanup.

### Phase 3: Analyse

**`POST /api/v1/imports/{job_id}/analyse`**

Accepts JSON body:
- `manifest`: list of duplicate-file entries (relative_path, filename, content_hash, duplicate_of)
- `image_type`: default image type hint (`battlemap` or `scene`)

**Processing:**
1. Validate job exists and is in `uploading` state
2. Walk staging directory to discover all saved files
3. Merge discovered paths with manifest entries
4. Run `analyse_upload` via `asyncio.to_thread(analyse_upload, ...)`
   - Runs `ImageParser.group_files()` on all paths
   - Generates preview thumbnails (120x120 JPEG) into `data/staging/{job_id}/.thumbs/`
5. Update `ImportJob` row: status → `staging`, store `analysis_result`
6. Return `ImportUploadResponse` with job_id and groups

**Client-side deduplication:** Before uploading, the frontend computes SHA-256 hashes of all image files and calls `POST /imports/check-hashes` to identify duplicates. Duplicate files are not uploaded; they're passed in the `manifest` so the backend can still include them in the analysis result (with `duplicate_of` set).

**Response shape:**
```json
{
  "job_id": "a1b2c3d4e5f67890",
  "total_files": 12,
  "groups": [
    {
      "author": "czepeku",
      "group_name": "Island Fort",
      "files": [
        {
          "relative_path": "czepeku/Island Fort/IslandFort_Night.jpg",
          "filename": "IslandFort_Night.jpg",
          "detected_tags": [{"category": "lighting", "value": "night", ...}],
          "gridded": null,
          "grid_width": null,
          "grid_height": null,
          "subgroup": null,
          "image_type": "battlemap"
        }
      ]
    }
  ]
}
```

## Backend: Preview Thumbnail Endpoint

**`GET /api/v1/imports/{job_id}/preview/{relative_path:path}`**

Serves pre-generated thumbnails for the import preview UI.

- Looks up thumbnail in `.thumbs/` subdir of staging (uses UUID-based staging key: `Path(staging_key).stem + ".jpg"`)
- Path traversal guard: resolved path must be within staging directory
- Falls back to serving the original staged file if thumbnail is missing
- Returns `FileResponse` with `image/jpeg` content type

## Backend: Confirm All Endpoint

**`POST /api/v1/imports/{job_id}/confirm-all`**

Confirms all pending groups in one request:
```json
{
  "groups": [
    { "author": "...", "group_name": "...", "files": [...] },
    { "author": "...", "group_name": "...", "files": [...] }
  ]
}
```

Submits all groups for processing immediately.

## Backend: Status Endpoint

**`GET /api/v1/imports/{job_id}/status`**

Returns current job status with per-group progress. Status is read directly from `ImportJob.status` in the database (authoritative, not derived).

Response includes `group_job_id` for each group, enabling robust frontend matching.

```json
{
  "job_id": "a1b2c3d4e5f67890",
  "status": "active",
  "groups": [
    {
      "group_job_id": "abc123",
      "group_name": "Island Fort",
      "total_files": 6,
      "processed_files": 6,
      "failed_files": 0,
      "status": "completed",
      "group_id": 42
    }
  ],
  "detected_group_count": 3
}
```

## Backend: Analysis Endpoint

**`GET /api/v1/imports/{job_id}/analysis`**

Returns the stored analysis for reconnection — rebuilds the preview UI when a dialog is reopened after the page was closed during/after upload. Only available for staging/active jobs that have `analysis_result` data with the full `groups` key.

## Backend: Fail Endpoint

**`POST /api/v1/imports/{job_id}/fail`**

Marks a job as `failed` with a client-provided error message. Guards against transitioning from `active` or already-terminal states — only valid from `uploading` or `staging`.

Accepts JSON body: `{ "error_message": "Upload failed: ..." }`

Sets `ImportJob.status = "failed"`, `ImportJob.error_message = error_message`, and `ImportJob.completed_at = now()`. Cleans up the staging directory.

`error_message` is surfaced in `ImportJobSummary.error_message` (via `/active` and `/status` endpoints) and shown in `ImportSummaryDialog`.

## Backend: Cancel Endpoint

**`POST /api/v1/imports/{job_id}/cancel`**

Cancels an import job. Cancels any running group jobs and runs `transition_job_status()` for terminal groups or sets `cancelled` directly.

## Auto-Confirm Retry

When the auto-confirm effect in `useImportState` sends `POST /confirm-all` and receives a network or server error, it retries with exponential backoff (delays: 1 s, 2 s, 4 s — up to 3 retries). If all retries fail, it calls `POST /{job_id}/fail` to mark the job as failed on the backend, then transitions the frontend dialog to the `done` (error) state.

## Connection Lost Indicator

`useActiveImports` tracks consecutive poll failures on the `/imports/active` endpoint using `consecutiveFailuresRef`. After 3 consecutive failures, `connectionLost` is set to `true`. The `ActivityDock` renders a `WifiOff` icon while this flag is set. `connectionLost` is reset to `false` on the first successful response.

## Crash Supervision / Backend Restart Robustness

### Server startup: broken jobs

On every startup, `mark_interrupted_jobs()` (called from the FastAPI lifespan) transitions any job in `uploading`, `staging`, or `active` to `broken`. These jobs were interrupted mid-flight and cannot be resumed. The frontend treats `broken` identically to `failed` — the `ImportSummaryDialog` is shown so the user can see what happened before dismissing.

### Frontend: stale terminal job reconnect blocked

`useImportPersistence` prevents reconnecting to jobs that are already in a terminal state (`completed`, `failed`, `cancelled`, `expired`, `broken`) when the page is reloaded. This avoids ghost dialogs reopening for already-resolved jobs.

### Crash loop supervision

`scripts/start.py` (used in the development/server deployment mode) and `backend/pyinstaller/entry.py` (used in the Electron app) both include crash supervision:
- **`start.py`**: Spawns backend and frontend as subprocess children. If either crashes, it is restarted with exponential backoff. Gives up after 10 crashes within 5 minutes.
- **`entry.py`**: Restarts the uvicorn server in-process on crash. Same 10-crash-in-5-minute limit. Note: in-process restart means corrupted module-level state (singletons, connection pools) persists across restarts — this is the correct tradeoff for Electron where process isolation would require re-bundling the Python runtime.

## Group Detection

See [parser.md](parser.md) for the full algorithm. Summary:

1. **Folder-based:** Parser detects group from folder hierarchy → `group_from_folder=True`
2. **Subgroup merge:** Multiple groups under same top folder where one group name matches the folder → merge into single group
3. **All-generic folders:** When all intermediate folders are utility names → top folder is the group
4. **Prefix-based fallback:** For flat files, merge by common filename prefix within same parent folder

## Frontend: ImportDialog

The import dialog handles upload only. There is no pre-import review step — groups are auto-confirmed immediately after analysis.

**Design philosophy:** The parser's group detection (ADR-006) handles the dominant use case (organized creator packs) accurately. Pre-import editing is tedious and "blind" — users would be editing unenriched metadata before ML enrichment (grid detection, CLIP embedding, color extraction) has run. Post-import review via `EditGroupDialog` shows enriched metadata, making edits more informed.

Three dialog states:

### Upload State (`uploading`)
- File picker button (accepts `.jpg`, `.jpeg`, `.png`, `.webp`, `.zip`)
- Folder picker button (via `webkitdirectory`)
- Image type toggle (battlemap / scene) — applied to all files
- Shows spinner and per-batch progress during upload
- Displays error if upload fails

### Processing State (`active`)
- Per-group status list: spinner while running, checkmark when complete
- Dialog can be closed — ActivityDock tracks progress
- `'preview'` is a transient internal state only (auto-confirm fires via useEffect before any render)

### Done State (`completed`, `failed`, `cancelled`, `expired`)
- Shows final status
- "Close" button → refreshes gallery queries

## Frontend State Hooks

| Hook | Purpose |
|------|---------|
| `useImportState` | Main state orchestrator: groups, dialog state, confirm handlers |
| `useImportUpload` | File upload handling, analysis response mapping |
| `useImportPolling` | Polls backend during processing, matches by `group_job_id` |
| `useImportPersistence` | localStorage save/restore, reconnection with backend sync |
| `useActiveImports` | Import tray: merges localStorage + backend data, polling |

## Data Flow

```
POST /init → job created (uploading)
POST /upload-batch ×N → files staged
POST /analyse → analyse_upload (sync) → ImportUploadResponse (staging)
  → useImportState auto-confirm effect fires
  → Empty authors filled as "Unknown" (frontend-only default — the backend accepts null/empty author)
  → POST /confirm-all → all groups submitted at once
  → process_import_job runs async via JobRunner
  → transition_job_status() → active → completed
  → Toast notification fires
  → Images immediately visible in gallery
  → ActivityDock entry dismissed
```

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are cleaned up by:
- The periodic `cleanup_staging` scheduler task (every 6h, removes dirs older than 24h)
- The `expire_stale_jobs` scheduler task (every 6h, cleans staging for expired jobs)
- `POST /cancel` endpoint (removes staging dir)
- `_finalize_import_job()` pipeline function (cleans staging after all groups processed)
