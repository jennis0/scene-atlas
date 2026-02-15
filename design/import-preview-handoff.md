# Import Preview UX - Implementation Handoff

## What Was Done

All code has been written but **nothing has been tested yet**. The changes span backend and frontend.

### Backend Changes (4 files)

1. **`backend/flows/tasks/image_processing.py`** — Added `generate_preview_thumbnail` task
   - Creates 120x120 JPEG thumbnails in `data/staging/{job_id}/.thumbs/`
   - Safe filename: slashes replaced with `__`, stem + `.jpg`
   - Called as a Prefect task during analysis

2. **`backend/flows/ingestion.py`** — Two changes:
   - **`analyse_upload` flow**: Now generates preview thumbnails for each file after grouping, adds `preview_thumbnail` key to each file's result dict
   - **`process_import_group` flow**: Parameter changed from `file_paths: list[str]` to `files: list[dict]`. No longer re-parses filenames. Uses per-file metadata from the confirm request directly, passing it straight through to `process_single_image(metadata=...)`.
   - Also added import for `generate_preview_thumbnail`

3. **`backend/app/models/schemas.py`** — Schema changes:
   - Added `grid_width` and `grid_height` to `ImportFileInfo` (analysis response)
   - Added new `ImportConfirmFile` model (per-file metadata: relative_path, tags, gridded, grid_width, grid_height, sub_variant)
   - Changed `ImportConfirmRequest.files` from `List[str]` to `List[ImportConfirmFile]`

4. **`backend/app/api/imports.py`** — Two changes:
   - **Confirm endpoint**: Updated to use new schema. Calls `file_info.model_dump()` to serialize each file, passes as `files` parameter to Prefect deployment (was `file_paths`). Added `FileResponse` import.
   - **New preview endpoint**: `GET /{job_id}/preview/{relative_path:path}` — Serves pre-generated thumbnails from `.thumbs/` subdir in staging. Path traversal guard included. Falls back to original staged file if thumbnail missing.

### Frontend Changes (2 files)

5. **`frontend/src/types/index.ts`** — Type updates:
   - Added `common_values: string | null` to `TagCategory`
   - Added `grid_width`, `grid_height` to `ImportFileInfo`
   - Added `TagData` interface (shared tag shape)
   - Added `ImportConfirmFile` and updated `ImportConfirmRequest` to use it
   - Added `EditableFileState` (with `excluded` field) and `EditableGroupState` (with `skip`, `id` fields)

6. **`frontend/src/components/ImportDialog.tsx`** — Complete rewrite:
   - **Style**: Light Gallery with emerald accent (clean, spacious, category-colored tags)
   - **State model**: Single `EditableGroupState[]` as source of truth (replaces split `uploadResponse` + `groups`)
   - **New features**:
     - Thumbnail previews (80x80, from preview endpoint)
     - Per-file tag removal (X on badges) and addition (inline category→value dropdown)
     - Grid status 3-state toggle (Grid / Gridless / ?)
     - File exclusion (hover X, dims row, shows Restore)
     - Group skip (via DropdownMenu on tab, shows placeholder)
     - Group merge (via DropdownMenu, combines file lists)
     - Default author bar (appears when any group has empty author)
   - **Confirm flow**: Builds `ImportConfirmFile[]` from editable state, sends full per-file metadata
   - **Sub-components**: `TagPicker`, `GridToggle`, `FileCard` (all defined in same file)
   - `Badge` is imported but unused — can be removed (tags use custom styled spans for category colors)

### Data Flow (Before → After)

**Before:**
```
Upload → analyse_upload → ImportUploadResponse (auto-detected metadata)
→ User edits author/group name only
→ Confirm sends { author, variant_group_name, files: string[] }
→ process_import_group RE-PARSES each file for tags/gridded
→ process_single_image(metadata={re-parsed})
```

**After:**
```
Upload → analyse_upload (+ thumbnail generation) → ImportUploadResponse
→ User edits everything (tags, grid, exclusions, skip, merge)
→ Confirm sends { author, variant_group_name, files: ImportConfirmFile[] }
→ process_import_group uses metadata AS-IS (no re-parsing)
→ process_single_image(metadata={from confirm request})
```

## What Needs Doing Next

### 1. Verify TypeScript Compilation
Run `npm run build` or `npx tsc --noEmit` in `frontend/`. Fix any type errors. Likely issues:
- The `Badge` import in ImportDialog is unused — remove it
- The `tagApi` import may not be exported from `@/lib/api` — verify
- `TagCategory` type now has `common_values` — check if existing code using `TagCategory` breaks

### 2. Verify Backend Runs
- Start the backend (`uvicorn backend.app.main:app`) and verify no import errors
- Check that the `ImportConfirmFile` is properly exported from schemas (it's imported in `imports.py`)
- The Prefect deployment parameter change (`file_paths` → `files`) means **deployments must be re-registered** via `uv run python -m backend.flows.deploy`

### 3. Test End-to-End
Full test requires: Docker infrastructure running, Prefect deployments registered, worker running, backend running, frontend dev server running.

**Test cases:**
- Upload a folder → verify thumbnails appear in preview
- Edit tags (remove, add) → confirm → check DB records have edited tags
- Toggle grid status → confirm → check DB has user's choice
- Exclude a file → confirm → verify it's not processed
- Skip a group → Import All → verify skipped group isn't submitted
- Merge two groups → confirm → verify combined files processed as one group
- Test with zip upload
- Test with single group (no tab bar should appear)
- Test author bar: upload files where parser can't detect author → apply default

### 4. Dark Mode
The new ImportDialog uses hardcoded light colors (e.g., `bg-white`, `text-slate-800`, `bg-amber-50`). These won't look right in dark mode. If the app supports dark mode, the tag colors, file cards, and tag picker dropdown need dark variants. This can be done later with `dark:` prefixes.

### 5. Update Design Docs
Update `design/web-import.md` to reflect:
- The new data flow (no re-parsing on confirm)
- The preview thumbnail generation during analysis
- The extended confirm schema
- The new preview endpoint

Update `design/ingestion.md` to reflect:
- `process_import_group` now accepts `files: list[dict]` not `file_paths: list[str]`
- No parser dependency in the processing flow for web imports

### 6. Remove Unused Badge Import
Line 21 of ImportDialog.tsx imports `Badge` but it's no longer used (tags use custom inline styles for category colors). Remove to avoid lint warnings.

## Files Modified (Summary)

| File | Change |
|------|--------|
| `backend/flows/tasks/image_processing.py` | Added `generate_preview_thumbnail` task |
| `backend/flows/ingestion.py` | Thumbnails in `analyse_upload`, metadata passthrough in `process_import_group` |
| `backend/app/models/schemas.py` | Added `ImportConfirmFile`, extended `ImportFileInfo`, updated `ImportConfirmRequest` |
| `backend/app/api/imports.py` | New preview endpoint, updated confirm endpoint |
| `frontend/src/types/index.ts` | New types: `TagData`, `EditableFileState`, `EditableGroupState`, `ImportConfirmFile` |
| `frontend/src/components/ImportDialog.tsx` | Complete rewrite with all preview editing features |
