# Ingest Error & Warning Reporting — Handover Document

**Date:** 2026-03-04
**Status:** Planned — ready for implementation
**Branch:** Create a new worktree for this feature

## Summary

The ingest pipeline has strong internal error handling (per-file error classification, DB persistence in `ImportGroupJob.file_errors`, API exposure via `/status`), but significant gaps remain in what actually reaches the user. This feature closes those gaps so that every skipped file, failed image, and pipeline-level warning is:

1. **Persisted** in the database
2. **Surfaced** to the user at import completion and accessible later via the activity dock
3. **Logged** with full technical detail on the backend

## What the User Should See

### At import completion — ImportDetailsDialog opens automatically

The current `ImportDonePane` ("All done, X groups imported") is replaced. When processing finishes, the import dialog closes and `ImportDetailsDialog` opens — the same dialog accessible later from the activity dock.

**Header area:**
- Status: "Import Complete" (green) / "Import Complete — X issues" (amber) / "Import Failed" (red)
- Source label (zip filename or folder name)
- Stats line: `47 images imported · 312 MB · took 2m 14s`

**Groups table** (existing pattern, already works):
- Per-group: name, OK count, failed count, status badge

**Issues sections** (collapsible, only shown when relevant):
- **Skipped files** — upload-phase rejects (bad format, oversized, bad magic bytes). Each entry shows filename and reason.
- **Errors** — processing failures (corrupt image, out of memory, etc.). Each entry shows filename, relative path, and reason.
- **Warnings** — non-fatal issues (Qdrant semantic index failure). Each entry shows filename, relative path, and reason.

**Footer:**
- "Review imported images" button → opens EditGroupDialog
- "Close" button
- "Cancel & Clean Up" button (only for failed/broken jobs)

### In the Activity Dock

- **Completed clean:** Green check icon, "Review import ›" (unchanged)
- **Completed with issues:** Amber warning icon, "X imported, Y issues ›"
- Clicking either opens ImportDetailsDialog

### In backend logs

- Per-file errors: `logger.exception()` with stack trace (mostly already exists)
- Per-file warnings: `logger.warning()` with filename, relative_path, stage, reason
- Group summary: `logger.info("Group abc (Forest Maps): 45 ok, 2 failed, 2 errors, 3 warnings")`

---

## Implementation — Three Stages

### Stage 1: Agree on user-facing requirements ✅ DONE

See "What the User Should See" above. Key decisions made:
- `ImportDonePane` is removed — replaced by `ImportDetailsDialog` opening automatically
- `ImportDetailsDialog` is a single component adapting to job status (clean/issues/failed/broken)
- Same dialog accessible both at completion time and later from the activity dock
- File lists (not just counts) for all issues — counts are section headers
- Stats include: total imported count, total file size, ingest duration

### Stage 2: Backend & data changes

Everything below needs implementing. The line numbers reference the codebase as of 2026-03-04.

#### What already works (verified, no changes needed)

- **Server-side limit violations** (per-file size, total upload size, max file count, zip safety): `HTTPException(413)` → frontend catches → calls `POST /fail` → job marked `failed` with error message → staging cleaned up via `shutil.rmtree`. Error messages are user-friendly and include filenames.
- **Per-file error classification**: `backend/pipeline/error_classifier.py` maps exceptions to user-friendly `{reason, stage, detail}` dicts. Comprehensive coverage of PIL errors, file system errors, memory errors, stage-specific fallbacks.
- **Error persistence**: `ImportGroupJob.file_errors` stores per-file errors as JSON text. Returned via `/status` API.
- **Frontend error display for failed jobs**: `ImportSummaryDialog` fetches `/status` and renders per-group table + per-file error list for failed/broken jobs.

#### What's missing (needs implementing)

| Gap | Impact |
|-----|--------|
| `file_errors` use bare filename only (`Path(rel_path).name`) | User can't identify which file in a nested folder structure |
| No warning concept — only errors | Upload-phase skips, Qdrant non-fatal failures are invisible |
| Upload-phase skipped files not persisted | Lost when import dialog closes; inaccessible from activity dock |
| Qdrant non-fatal failures not surfaced | Images saved to DB but missing from semantic search — user has no idea |
| `ImportJobSummary` lacks `failed_files` count | Activity dock can't distinguish clean vs completed-with-issues |
| Total file size not tracked on ImportJob | Can't show "312 MB" in stats line |
| Frontend polling discards `file_errors` | `useImportPolling` updates counts but not error details |

---

#### Step 1: Extend `FileError` schema

**File:** `backend/app/models/schemas.py` (line 434)

```python
class FileError(BaseModel):
    """Per-file error or warning detail within an import group."""
    filename: str
    relative_path: str | None = None     # Full path for user context
    reason: str
    stage: str
    severity: str = "error"              # "error" | "warning"
```

No DB migration needed — `ImportGroupJob.file_errors` is a JSON text column. Old dicts without `relative_path`/`severity` get Pydantic defaults (`None` and `"error"`).

#### Step 2: Thread `relative_path` through the pipeline

**File:** `backend/pipeline/ingestion.py`

**2a.** In `_run_group` (~line 1134), add `"relative_path": file_info["relative_path"]` to the metadata dict passed to `prepare_single_image`.

**2b.** In `prepare_single_image` (~line 196), read `relative_path = metadata.get("relative_path")` and include it in both success (line ~478) and failure (line ~490) return dicts as `"relative_path": relative_path`.

**2c.** Update all `all_file_errors.append(...)` calls to include `relative_path` and `severity`:

Location 1 (~line 1100 — missing staging file):
```python
all_file_errors.append({
    "filename": Path(file_info["relative_path"]).name,
    "relative_path": file_info["relative_path"],
    "reason": "File was not found in staging",
    "stage": "copy",
    "severity": "error",
})
```

Location 2 (~line 1173 — failed batch results):
```python
rel_path = r.get("relative_path")
all_file_errors.append({
    "filename": Path(rel_path or r.get("original_image_path", "unknown")).name,
    "relative_path": rel_path,
    "reason": error_info.get("reason", r.get("error", "Unknown error")),
    "stage": error_info.get("stage", "unknown"),
    "severity": "error",
})
```

#### Step 3: Surface Qdrant non-fatal failures as warnings

**File:** `backend/pipeline/ingestion.py`

**3a.** Change `_process_batch` return signature from `tuple[list[dict], int]` to `tuple[list[dict], int, list[dict]]` — third element is a list of warning dicts.

**3b.** At ~line 777 (Qdrant save), `batch_save_to_qdrant` currently returns its result but it's not checked. Capture the return value and generate warnings on failure:
```python
qdrant_ok = batch_save_to_qdrant(qdrant_items)
if not qdrant_ok:
    for prep in all_successful:
        warnings.append({
            "filename": Path(prep.get("original_image_path", "unknown")).name,
            "relative_path": prep.get("relative_path"),
            "reason": "Saved but may not appear in semantic search until index is rebuilt",
            "stage": "qdrant_save",
            "severity": "warning",
        })
```

**3c.** Update `_run_group` call site (~line 1162):
```python
batch_results, _, batch_warnings = _process_batch(prepared_results)
all_file_errors.extend(batch_warnings)
```

#### Step 4: Persist upload-phase warnings in the database

**4a.** Add columns to `ImportJob`:

**File:** `backend/app/models/database.py` (~line 178)
```python
job_warnings = Column(Text, nullable=True)    # JSON list of warning dicts
total_file_size = Column(Integer, default=0)  # Accumulated bytes across all batches
```

**4b.** In upload-batch endpoint, persist backend-detected `skipped_invalid` as warnings:

**File:** `backend/app/api/imports.py` (~line 468)

After `_save_files_to_staging` returns `skipped_invalid`, append to `job.job_warnings` JSON:
```python
if skipped_invalid:
    existing = json.loads(job.job_warnings or "[]")
    new_warnings = [
        {"filename": name, "reason": "Not a supported image format (invalid file header)",
         "stage": "upload", "severity": "warning"}
        for name in skipped_invalid
    ]
    job.job_warnings = json.dumps(existing + new_warnings)
    db.commit()
```

Also update `job.total_file_size` from the `total_bytes` return value.

**4c.** Add `POST /imports/{job_id}/report-skipped` endpoint for client-side skips:

**File:** `backend/app/api/imports.py`

```python
class ReportSkippedFile(BaseModel):
    filename: str
    reason: str

class ReportSkippedRequest(BaseModel):
    files: list[ReportSkippedFile]
```

- Accepts `{files: [{filename, reason}]}`
- Appends to `job.job_warnings` JSON with `stage: "upload"`, `severity: "warning"`
- Frontend calls this once after all upload batches complete, before triggering analyse
- Guards: only valid from `uploading`/`staging` states

**File:** `frontend/src/hooks/useImportUpload.ts`

After all upload batches complete (before calling analyse), call:
```typescript
if (skippedFiles.length > 0) {
  await importApi.reportSkipped(jobId, skippedFiles.map(name => ({
    filename: name,
    reason: name.includes('too large') ? name : 'Not a supported image format'
  })))
}
```

Note: the current `skippedFiles` state mixes plain filenames (from magic byte check) with annotated strings like `"huge.png (too large, >2000MB)"` (from size check). The frontend should normalize these before sending.

#### Step 5: Enrich API responses

**File:** `backend/app/models/schemas.py`

Add to `ImportJobResponse`:
```python
job_warnings: list[FileError] = []   # Upload-phase and pipeline-level warnings
total_file_size: int = 0             # Total bytes across all uploaded files
```

Add to `ImportJobSummary`:
```python
failed_files: int = 0      # Total failed files across all groups
warning_count: int = 0     # Number of job-level warnings (upload skips, etc.)
```

**File:** `backend/app/api/imports.py`

- `/status` endpoint: populate `job_warnings` from `ImportJob.job_warnings` JSON; populate `total_file_size` from `ImportJob.total_file_size`
- `/active` endpoint: populate `failed_files` (sum `failed_files` across groups) and `warning_count` (len of parsed `job_warnings`)

#### Step 6: Fix analyse-step error to include filename

**File:** `backend/pipeline/ingestion.py` — in `analyse_upload()`

Wrap per-file processing with try/except that includes the filename:
```python
try:
    # ... existing per-file analysis logic ...
except Exception as e:
    raise ValueError(f"Failed to analyse '{rel_path}': {e}") from e
```

**File:** `backend/app/api/imports.py` — `/analyse` endpoint

Catch `ValueError` and return 422 with filename in detail.

This addresses the pending design doc item 2 in `design/upload-error-improvements-todo.md`.

#### Step 7: Frontend data plumbing

**7a.** `frontend/src/types/index.ts`

Add `file_errors` to `EditableGroupState`:
```typescript
file_errors?: Array<{
  filename: string
  relative_path?: string | null
  reason: string
  stage: string
  severity?: 'error' | 'warning'
}>
```

Update `ImportJobSummary` type with `failed_files: number` and `warning_count: number`.

Update `ImportJobResponse` type with `job_warnings` and `total_file_size`.

**7b.** `frontend/src/hooks/useImportPolling.ts`

Capture `file_errors` from poll responses into group state (add to the `setGroups` updater at ~line 44):
```typescript
file_errors: gs.file_errors ?? g.file_errors,
```

On terminal state transition (~line 62), do a final fetch to ensure all errors are captured before transitioning to done.

**7c.** `frontend/src/hooks/useImportUpload.ts`

Capture `skipped_invalid` from `BatchUploadResponse` (currently discarded at ~line 232):
```typescript
const response = await importApi.uploadBatch(...)
if (response.skipped_invalid?.length) {
  setSkippedFiles(prev => [...prev, ...response.skipped_invalid])
}
```

Call `/report-skipped` after all batches complete.

**7d.** `frontend/src/hooks/useActiveImports.ts`

Add `failedFiles: number` and `warningCount: number` to `ActiveImportJob` (~line 25). Populate in `backendToActiveJob` (~line 203) from the new `ImportJobSummary` fields.

#### Step 8: Logging

**File:** `backend/pipeline/ingestion.py`

- Add `logger.warning(...)` for each Qdrant non-fatal failure warning
- Update group summary at end of `_run_group` to include warning counts:
  ```
  Group abc (Forest Maps): 45 ok, 2 failed, 2 errors, 3 warnings
  ```

#### Step 9: Tests

- **Schema:** `FileError` backward compat — old dicts without `relative_path`/`severity` get defaults
- **Pipeline:** `_process_batch` returns warnings when Qdrant fails; `_run_group` stores `relative_path` in all error dicts
- **API:** `/status` returns enriched `file_errors`; `/active` includes `failed_files` and `warning_count`; `/report-skipped` persists to `job_warnings`
- **Upload:** `skipped_invalid` persisted to `job_warnings` in upload-batch handler

---

### Stage 2 Files to Modify

| File | Changes |
|------|---------|
| `backend/app/models/database.py` | Add `job_warnings`, `total_file_size` columns to `ImportJob` |
| `backend/app/models/schemas.py` | Extend `FileError` with `relative_path`/`severity`; add `ReportSkippedRequest`; add fields to `ImportJobResponse` and `ImportJobSummary` |
| `backend/pipeline/ingestion.py` | Thread `relative_path` through prepare → batch → errors; Qdrant warnings; `_process_batch` signature change; logging; analyse error filename |
| `backend/app/api/imports.py` | New `/report-skipped` endpoint; persist upload skips to `job_warnings`; accumulate `total_file_size`; populate new response fields; analyse error 422 |
| `frontend/src/types/index.ts` | Add `file_errors` to `EditableGroupState`; update `ImportJobSummary` and `ImportJobResponse` types |
| `frontend/src/hooks/useActiveImports.ts` | Add `failedFiles`, `warningCount` to `ActiveImportJob`; populate from summary |
| `frontend/src/hooks/useImportPolling.ts` | Capture `file_errors` during polling; final fetch on terminal transition |
| `frontend/src/hooks/useImportUpload.ts` | Capture backend `skipped_invalid`; call `/report-skipped` |
| `frontend/src/lib/api.ts` | Add `importApi.reportSkipped()` method |

---

### Stage 3: Frontend design (NOT YET PLANNED)

Use the `frontend-design` skill to design:
- **ImportDetailsDialog** — evolved from `ImportSummaryDialog`, adapts to all job statuses (clean/issues/failed/broken). Replaces both `ImportSummaryDialog` and `ImportDonePane`.
- **ActivityDock** — visual indicator (icon/badge) for completed-with-issues jobs
- **ImportDialog** changes — auto-open ImportDetailsDialog on completion instead of showing ImportDonePane
- **Gallery.tsx** — routing logic: completed-with-issues jobs open ImportDetailsDialog; clean completed jobs open EditGroupDialog

Files to modify in Stage 3:
| File | Changes |
|------|---------|
| `frontend/src/components/ImportSummaryDialog.tsx` | Evolve into ImportDetailsDialog with multi-status support |
| `frontend/src/components/import/ImportDonePane.tsx` | Remove entirely |
| `frontend/src/components/ImportDialog.tsx` | Remove ImportDonePane usage; auto-open ImportDetailsDialog on completion |
| `frontend/src/components/ActivityDock.tsx` | `ImportStatusIcon` and `ImportStatusText` for completed-with-issues |
| `frontend/src/pages/Gallery.tsx` | `onOpenJob` routing for completed-with-issues |

---

## Implementation Order

1. Start a new worktree for this feature
2. **Stage 2 backend first** (steps 1–6, 8–9): schema, pipeline, API, logging, tests — can be developed and tested independently
3. **Stage 2 frontend** (step 7): data plumbing to capture and expose the new data
4. **Stage 3**: design and implement the UI changes
5. Run full test suite, linting (ruff, ESLint/Prettier), manual verification
6. Commit and create PR

## Manual Verification Checklist

1. **Clean import:** Upload valid images → "Import Complete" with no issues section → activity dock shows "Review import ›" → clicking opens EditGroupDialog
2. **Mixed import:** Upload valid images + a corrupt file + a .txt file → skipped files section shows .txt with reason → errors section shows corrupt file with relative path → activity dock shows "X imported, Y issues" → clicking opens ImportDetailsDialog with persisted data
3. **Qdrant down:** Stop Qdrant, upload images → warning appears about semantic search → images appear in gallery via FTS → warning persists in activity dock
4. **Size limit:** Upload a file exceeding max size → job marked as failed → error message in ImportDetailsDialog → staging cleaned up
5. **After dialog close:** Close the import dialog → open activity dock → click completed-with-issues job → ImportDetailsDialog shows all persisted errors/warnings

## Related Design Docs

- `design/upload-error-improvements-todo.md` — Item 2 (analyse filename) addressed by Step 6
- `design/import-state-machine.md` — Import job lifecycle and state transitions
- `design/ingestion.md` — Pipeline architecture and batch processing
