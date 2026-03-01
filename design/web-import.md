# Web Import Flow

## Overview

The web import allows users to upload images (files, folders, or zip archives) through the browser, review detected metadata, and confirm import into the system.

For state machine details, see [import-state-machine.md](import-state-machine.md).

## User Flow

```
Gallery → [Import button] → ImportDialog opens
  → Select files or folder (or .zip)
  → Files uploaded to staging in batches (init → upload-batch ×N → analyse)
  → Backend analyses files, groups into image groups, generates preview thumbnails
  → Dialog shows tabbed preview (one tab per image group)
  → User reviews/edits author, group name, image types per file
  → User can exclude files, skip groups, merge groups, split groups
  → User confirms one group or all groups
  → Confirm sends full per-file metadata + remaining_groups list
  → Async processing starts via JobRunner
  → Progress indicator (polling with group_job_id matching)
  → If pending groups remain → back to preview (awaiting_input)
  → Done → gallery refreshes
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

The import dialog is a **group management tool** — it handles file organization into groups before import. Per-file metadata editing (tags, grid, name, subgroup) is deferred to post-import via `ImageViewer` and `EditGroupDialog` (import-review mode).

**Design philosophy:** The import dialog intentionally avoids per-file metadata editing because (a) it doesn't scale — imports can have hundreds of files, making per-file editing tedious, (b) users would be editing "blind" before ML enrichment (grid detection, CLIP embedding, color extraction) has run, and (c) post-import review via `EditGroupDialog` and `ImageViewer` shows enriched metadata, making edits more informed. The import dialog focuses on the things only the user can decide upfront: grouping, authorship, and image type.

Four dialog states (mapped from backend status via `backendStatusToDialogState()`):

### Upload State (`uploading`)
- File picker button (accepts `.jpg`, `.jpeg`, `.png`, `.webp`, `.zip`)
- Folder picker button (via `webkitdirectory`)
- Shows spinner during upload
- Displays error if upload fails

### Preview State (`staging` or `awaiting_input`)
- **Default Author bar** above tabs: Input + "Apply to Empty" button fills all empty author fields
- Tab bar if multiple image groups detected (tab per group)
  - Each tab has a DropdownMenu with "Skip Group" and "Merge into [other group]"
  - Skipped groups show dimmed tab with strikethrough, content replaced with "Skipped" + Undo
- Each tab shows:
  - Editable **Author** text input (pre-filled from detection, may be empty)
  - Editable **Group Name** text input (pre-filled)
  - Compact file cards (`ImportFileCard`) with thumbnail, name, type toggle, duplicate indicator
  - Simplified toolbar (`ImportFileToolbar`) with search, select, bulk actions
  - Subgroup headings (read-only)
- "Import This Group" button (disabled if author is empty)
- "Import All" button if multiple pending groups

### Processing State (`active`)
- Per-group status: spinner while running, checkmark when complete
- Processing indicator survives dialog close (state preserved in localStorage)
- Re-open dialog to check progress

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
POST /upload → analyse_upload (sync) → ImportUploadResponse (staging)
  → User manages groups (merge, split, skip, exclude, set author/type)
  → Auto-detected tags/grid hints pass through unchanged
  → POST /confirm sends { author, group_name, files, remaining_groups }
  → process_import_group runs async via JobRunner
  → transition_job_status() → active (has running groups)
  → Group completes → transition_job_status() → awaiting_input or completed
  → If awaiting_input: user confirms more groups → active again
  → All groups done → completed or failed
  → Post-import: user reviews enriched metadata via EditGroupDialog
```

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are cleaned up by:
- The periodic `cleanup_staging` scheduler task (every 6h, removes dirs older than 24h)
- The `expire_stale_jobs` scheduler task (every 6h, cleans staging for expired jobs)
- `POST /cancel` endpoint (removes staging dir)
- `POST /finalize` endpoint (removes staging dir)
