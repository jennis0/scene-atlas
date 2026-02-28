# Web Import Flow

## Overview

The web import allows users to upload images (files, folders, or zip archives) through the browser, review detected metadata, and confirm import into the system.

For state machine details, see [import-state-machine.md](import-state-machine.md).

## User Flow

```
Gallery → [Import button] → ImportDialog opens
  → Select files or folder (or .zip)
  → Files uploaded to staging (two-phase: init + upload)
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

## Two-Phase Upload

### Phase 1: Init

**`POST /api/v1/imports/init`**

Creates a job in `uploading` status with an empty staging directory. Returns `{ job_id }`. This allows the frontend to start uploading files immediately and show progress.

### Phase 2: Upload

**`POST /api/v1/imports/upload`**

Accepts `multipart/form-data`:
- `files`: one or more image files or .zip archives
- `relative_paths` (optional): JSON array of relative paths (from `webkitRelativePath` or zip structure)
- `job_id` (optional): ID from init endpoint. If provided, reuses the existing job.

**Processing:**
1. If `job_id` not provided, generate one (UUID hex, 16 chars)
2. Create staging directory: `data/staging/{job_id}/`
3. For each file:
   - If `.zip`: extract, skip `__MACOSX`/`._` files, filter to supported formats
   - Otherwise: save to staging preserving relative path structure
4. Run `analyse_upload` synchronously via `JobRunner.run_sync()`
   - Runs `ImageParser.group_files()` on all saved relative paths
   - Generates preview thumbnails (120x120 JPEG) into `data/staging/{job_id}/.thumbs/`
5. Create or update `ImportJob` row (status: `staging`, `pending_groups = len(groups)`)
6. Store analysis result for reconnection (`analysis_result` JSON)
7. Return `ImportUploadResponse` with job_id and groups

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

The import dialog is a **group management tool** — it handles file organization into groups before import. Per-file metadata editing (tags, grid, name, subgroup) is deferred to post-import via `ImageViewer` and `EditGroupDialog` (import-review mode). See [plan-simplify-import.md](plan-simplify-import.md) for rationale.

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
