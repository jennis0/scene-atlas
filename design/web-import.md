# Web Import Flow

## Overview

The web import allows users to upload images (files, folders, or zip archives) through the browser, review detected metadata, and confirm import into the system. It replaces the CLI-only `run_ingestion.py` for ad-hoc imports.

## User Flow

```
Gallery → [Import button] → ImportDialog opens
  → Select files or folder (or .zip)
  → Files uploaded to staging
  → Backend analyses files, groups into image groups, generates preview thumbnails
  → Dialog shows tabbed preview (one tab per image group)
  → User reviews/edits author, group name, tags, grid status, image type per file
  → User can exclude files, skip groups, merge groups
  → User confirms one group or all groups
  → Confirm sends full per-file metadata (no re-parsing on backend)
  → Async processing starts
  → Progress indicator (polling)
  → Done → gallery refreshes
```

## Backend: Upload Endpoint

**`POST /api/v1/imports/upload`**

Accepts `multipart/form-data`:
- `files`: one or more image files or .zip archives
- `relative_paths` (optional): JSON array of relative paths (from `webkitRelativePath` or zip structure)

**Processing:**
1. Generate `job_id` (UUID hex, 16 chars)
2. Create staging directory: `data/staging/{job_id}/`
3. For each file:
   - If `.zip`: extract, skip `__MACOSX`/`._` files, filter to supported formats
   - Otherwise: save to staging preserving relative path structure
4. Submit `analyse_upload` Prefect deployment (synchronous, `timeout=120`)
   - Runs `ImageParser.group_files()` on all saved relative paths
   - Generates preview thumbnails (120x120 JPEG) into `data/staging/{job_id}/.thumbs/`
5. Create `ImportJob` row in DB (status: `staging`)
6. Return `ImportUploadResponse` with job_id and groups

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
2. Serialize file metadata as dicts
3. Submit `process_import_group` Prefect deployment (async, `timeout=0`)
4. Store `flow_run_id` on ImportJob, set status to `running`
5. Return immediately

## Backend: Status Endpoint

**`GET /api/v1/imports/{job_id}/status`**

Returns current job status with per-group progress. Reads from ImportJob table counters (updated by the Prefect flow after each image).

## Group Detection

See [parser.md](parser.md) for the full algorithm. Summary:

1. **Folder-based:** Parser detects group from folder hierarchy → `group_from_folder=True`
2. **Subgroup merge:** Multiple groups under same top folder where one group name matches the folder → merge into single group
3. **All-generic folders:** When all intermediate folders are utility names → top folder is the group
4. **Prefix-based fallback:** For flat files, merge by common filename prefix within same parent folder

## Frontend: ImportDialog

The import dialog is a **group management tool** — it handles file organization into groups before import. Per-file metadata editing (tags, grid, name, subgroup) is deferred to post-import via `ImageViewer` and `EditGroupDialog` (import-review mode). See [plan-simplify-import.md](plan-simplify-import.md) for rationale.

Three states:

### Upload State
- File picker button (accepts `.jpg`, `.jpeg`, `.png`, `.webp`, `.zip`)
- Folder picker button (via `webkitdirectory`)
- Shows spinner during upload
- Displays error if upload fails

### Preview State
- **Default Author bar** above tabs: Input + "Apply to Empty" button fills all empty author fields
- Tab bar if multiple image groups detected (tab per group)
  - Each tab has a DropdownMenu with "Skip Group" and "Merge into [other group]"
  - Skipped groups show dimmed tab with strikethrough, content replaced with "Skipped" + Undo
- Each tab shows:
  - Editable **Author** text input (pre-filled from detection, may be empty)
  - Editable **Group Name** text input (pre-filled)
  - Compact file cards (`ImportFileCard`) with:
    - Preview thumbnail (clickable for lightbox)
    - Parsed name (read-only)
    - Subgroup badge (read-only, if detected)
    - Image type toggle (Battlemap / Scene)
    - Duplicate indicator (with skip/import toggle)
    - Selection checkbox + exclude button
  - Simplified toolbar (`ImportFileToolbar`) with:
    - Search/filter, select all/deselect all
    - Bulk set image type, bulk exclude, split to new group
    - Duplicate bulk controls
  - Subgroup headings (read-only, no rename/clear during import)
- "Import This Group" button (disabled if author is empty)
- "Import All" button if multiple pending groups

### Processing/Done State
- Per-group status: spinner while running, checkmark when complete
- Processing indicator survives dialog close (state preserved, pulsing dot on Import button)
- Re-open dialog to check progress
- "Close" button on completion → refreshes gallery queries

## Data Flow

```
Upload → analyse_upload (+ thumbnail generation) → ImportUploadResponse
  → User manages groups (merge, split, skip, exclude, set author/type)
  → Auto-detected tags/grid hints pass through unchanged (user doesn't edit these during import)
  → Confirm sends { author, group_name, files: ImportConfirmFile[] }
  → process_import_group uses metadata AS-IS (no re-parsing)
  → process_single_image(metadata={from confirm request directly})
  → Grid detection, CLIP, color extraction run during processing
  → Post-import: user reviews enriched metadata via EditGroupDialog (import-review mode)
```

Key design decision: The confirm request sends each file's **complete metadata** including auto-detected tags and grid hints from filename parsing. The import dialog does not expose editors for these — they pass through unchanged. The `process_import_group` flow does not re-parse filenames — it passes per-file metadata straight through to `process_single_image(metadata=...)`.

## Staging Cleanup

Staging directories (`data/staging/{job_id}/`) are created on upload and include a `.thumbs/` subdirectory for preview thumbnails. They are currently NOT automatically cleaned up after processing completes. This should be addressed — either:
- Clean up in `process_import_group` after all files are processed
- Add a periodic cleanup job for old staging dirs
- Clean up when the ImportJob transitions to `completed`
