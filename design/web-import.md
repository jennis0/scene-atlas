# Web Import Flow

## Overview

The web import allows users to upload images (files, folders, or zip archives) through the browser. After upload, groups are auto-confirmed and processing starts immediately. Images are hidden from the gallery until the user reviews them via EditGroupDialog.

For state machine details, see [import-state-machine.md](import-state-machine.md).

## User Flow

```
Gallery → [Import button] → ImportDialog opens
  → Select files or folder (or .zip)
  → Files uploaded to staging in batches (init → upload-batch ×N → analyse)
  → Backend analyses files, groups into image groups, generates preview thumbnails
  → Empty authors defaulted to "Unknown"
  → Auto-confirm all groups via POST /confirm-all (no user review step)
  → Dialog shows processing state (per-group spinners)
  → User can close dialog → ActivityDock tracks progress
  → Processing sets needs_review = true on all created images
  → On completion → toast notification fires ("Import complete — N groups, N images")
  → Toast "Review" action OR ActivityDock "Review import" → EditGroupDialog (import-review mode)
  → User reviews groups, clicks "Confirm Import"
  → needs_review cleared → images appear in gallery
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

**On failure:** The frontend calls `POST /{job_id}/cancel` to immediately clean up the staging directory.

### Phase 3: Analyse

**`POST /api/v1/imports/{job_id}/analyse`**

Accepts JSON body:
- `manifest`: list of duplicate-file entries (relative_path, filename, content_hash, duplicate_of)
- `image_type`: default image type hint (`battlemap` or `scene`)

**Processing:**
1. Validate job exists and is in `uploading` state
2. Walk staging directory to discover all saved files
3. Merge discovered paths with manifest entries
4. Run `analyse_upload` synchronously via `JobRunner.run_sync()`
   - Runs `ImageParser.group_files()` on all paths
   - Generates preview thumbnails (120x120 JPEG) into `data/staging/{job_id}/.thumbs/`
5. Update `ImportJob` row: status → `staging`, store `analysis_result`, set `pending_groups`
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

- Looks up thumbnail in `.thumbs/` subdir of staging (converts `relative_path` slashes to `__`, uses stem + `.jpg`)
- Path traversal guard: resolved path must be within staging directory
- Falls back to serving the original staged file if thumbnail is missing
- Returns `FileResponse` with `image/jpeg` content type

## Backend: Confirm Endpoint

**`POST /api/v1/imports/{job_id}/confirm`**

Accepts JSON body with **full per-file metadata** — the backend does not re-parse filenames:
```json
{
  "author": "czepeku",
  "group_name": "Island Fort",
  "remaining_groups": ["Coastal Cliffs", "Desert Oasis"],
  "files": [
    {
      "relative_path": "czepeku/Island Fort/IslandFort_Night.jpg",
      "tags": [{"category": "lighting", "value": "night", "confidence": 0.9, "source": "parser"}],
      "gridded": null,
      "grid_width": null,
      "grid_height": null,
      "subgroup": null,
      "image_type": "battlemap"
    }
  ]
}
```

**Processing:**
1. Validate each `file.relative_path` exists in staging
2. Set `job.pending_groups = len(remaining_groups)` (synced from frontend)
3. Create `ImportGroupJob` row (status: `running`)
4. Submit `process_import_group` via `JobRunner.submit()` (async)
5. Return `ImportJobResponse` with `group_job_id` for each group

The `remaining_groups` field tells the backend how many unconfirmed groups remain, accounting for any merges/splits the user did in the preview UI.

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

Sets `pending_groups = 0` and `all_confirmed = True`.

## Backend: Status Endpoint

**`GET /api/v1/imports/{job_id}/status`**

Returns current job status with per-group progress. Status is read directly from `ImportJob.status` in the database (authoritative, not derived).

Response includes `group_job_id` for each group, enabling robust frontend matching.

```json
{
  "job_id": "a1b2c3d4e5f67890",
  "status": "awaiting_input",
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
  "detected_group_count": 3,
  "pending_group_count": 2
}
```

## Backend: Analysis Endpoint

**`GET /api/v1/imports/{job_id}/analysis`**

Returns the stored analysis for reconnection — rebuilds the preview UI when a dialog is reopened after the page was closed during/after upload. Only available for staging/active/awaiting_input jobs that have `analysis_result` data with the full `groups` key.

## Backend: Finalize Endpoint

**`POST /api/v1/imports/{job_id}/finalize`**

Explicitly marks a job as complete. Sets `pending_groups = 0` and runs `transition_job_status()`. Rejects jobs with running groups.

## Backend: Cancel Endpoint

**`POST /api/v1/imports/{job_id}/cancel`**

Cancels an import job. Cancels any running group jobs, sets `pending_groups = 0`, and runs `transition_job_status()` for terminal groups or sets `cancelled` directly.

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

## Review-Gating Mechanism

All images created by the import pipeline have `needs_review = True` set. The gallery search filters these out by default (`exclude_needs_review=True` on `GET /search` and `GET /facets`). Images become visible only after the user confirms them.

**Confirm-review endpoint:** `POST /api/v1/groups/confirm-review` accepts `{ group_ids: int[] }` and clears `needs_review` on all images in those groups. Called by EditGroupDialog when user clicks "Confirm Import" in import-review mode.

**`needs_review` column:** Already existed on `Image` table (`database.py`) with an index. The import pipeline now sets it to `True`; the confirm-review endpoint sets it back to `False`.

## Data Flow

```
POST /init → job created (uploading)
POST /upload-batch ×N → files staged
POST /analyse → analyse_upload (sync) → ImportUploadResponse (staging)
  → useImportState auto-confirm effect fires
  → Empty authors filled as "Unknown"
  → POST /confirm-all → all groups submitted at once
  → process_import_job runs async via JobRunner
  → Images saved with needs_review = True
  → transition_job_status() → active → completed
  → Toast notification fires
  → User clicks "Review" → EditGroupDialog (import-review mode)
  → User clicks "Confirm Import" → POST /groups/confirm-review
  → needs_review cleared → images visible in gallery
  → ActivityDock entry dismissed
```

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are cleaned up by:
- The periodic `cleanup_staging` scheduler task (every 6h, removes dirs older than 24h)
- The `expire_stale_jobs` scheduler task (every 6h, cleans staging for expired jobs)
- `POST /cancel` endpoint (removes staging dir)
- `POST /finalize` endpoint (removes staging dir)
