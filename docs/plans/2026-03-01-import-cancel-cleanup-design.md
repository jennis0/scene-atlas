# Import Cancel & Cleanup Design

**Date:** 2026-03-01
**Status:** Approved

## Problem

When an import job fails due to a server crash, the job is left stuck in `uploading` or `active` state. The ActivityDock forbids dismissing non-terminal imports, so users have no way to clear these stuck jobs. Additionally, there was no way to cancel an import that had already started processing and roll back the imported data.

## Solution

Two complementary features:

1. **Crash detection on startup** — mark stuck imports as `broken` so they're actionable
2. **Cancel-with-cleanup** — allow any non-completed import to be cancelled with full rollback of imported images, files, and Qdrant embeddings

---

## Part A: `broken` Status

### What it is
A new terminal status value for `ImportJob`. No DB schema migration needed — `status` is a plain `String` column.

### When it's set
At server startup, after the JobRunner is initialised, a new `mark_interrupted_jobs()` function runs and:
- Finds all `ImportJob` rows in `uploading` or `active` states (these require live background threads that are now dead)
- Sets `status = "broken"`, `error_message = "Server was restarted before this import could complete"`
- For `active` jobs: also marks any child `ImportGroupJob` rows in `running` state as `failed`
- Sets `completed_at = now()`
- Leaves `staging` and `awaiting_input` jobs alone (their data is intact; frontend can reconnect)

### State machine
`broken` is added as a terminal state alongside `completed`, `failed`, `cancelled`, `expired`. The transition function in `import_state.py` must guard against transitioning out of `broken`.

---

## Part B: Cancel-with-Cleanup

### Image tracking
To know which images to roll back, we add `import_job_id` (nullable String, FK to `import_jobs.id`) to the `images` table.

**Migration:** new Alembic migration (next version after 011) adds the column with an index.

**Pipeline changes:** `import_job_id` flows through the ingestion chain as part of the `metadata` dict:
- `_run_group()` receives `job_id` and adds it to the metadata passed to `prepare_single_image()`
- `prepare_single_image()` includes `import_job_id` in the returned `image_data` dict (both new-image and reuse-image paths)
- `_save_image_to_db()` sets `image.import_job_id` from `image_data`
- Signatures for `batch_save_to_database()` and `_process_batch()` accept an optional `import_job_id` to pass through, OR (simpler) it rides in the `image_data` dict with no signature changes to batch functions

Duplicate images ("reuse path") also get tagged. They create new `Image` rows sharing a `storage_key` with the original, so tagging lets us delete the row without deleting the shared file (check is: `SELECT COUNT(*) FROM images WHERE storage_key = X AND id != deleted_id`).

### Enhanced cancel endpoint
`POST /imports/{job_id}/cancel` works for all non-`completed` states (including `broken`, `failed`, `active`, `awaiting_input`, `staging`, `uploading`).

Cleanup steps:
1. Verify job is not `completed` (409 if so)
2. Collect all `Image` rows where `import_job_id = job_id`
3. For each image: if its `storage_key` has no other referencing Image rows → delete physical file and thumbnail from disk
4. Batch-delete those image IDs from Qdrant
5. Delete the Image rows from DB (cascades tags/colors)
6. Delete now-empty ImageGroups linked via `ImportGroupJob.created_group_id` for this job
7. Mark all `ImportGroupJob` rows as `cancelled`
8. Delete staging directory `data/staging/{job_id}/`
9. Mark `ImportJob.status = "cancelled"`, set `completed_at`

**Race condition (best-effort):** if a background thread inserts more images after step 2, `_finalize_import_job()` is updated to detect `job.status == "cancelled"` and run a second cleanup sweep for any remaining `import_job_id = job_id` images.

---

## Frontend Changes

### ActivityDock.tsx

**Status handling:**
- Add `broken` to `isTerminal` check
- `canCancel` extended to: `uploading | staging | active | awaiting_input | broken | failed`
- `canDismiss` removed for `failed` state (users should use cancel-with-cleanup instead of silent dismiss)
- New `broken` icon: amber `AlertTriangle` from lucide-react

**Confirmation dialog:**
- When cancel is triggered and `processedFiles > 0`, show a confirmation dialog:
  *"This will permanently delete [N] imported images. This cannot be undone."*
- Proceed button: "Delete & Cancel Import"
- Cancel jobs with no processed files cancel silently (no confirmation needed)

**Broken state message:**
- In the ImportJobCard, when `status === 'broken'`, show sub-text: *"Interrupted — server was restarted"*

### Import API client (importApi)
No new endpoint needed — `/cancel` is reused. The client already calls `importApi.cancel(jobId)`.

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `backend/alembic/versions/013_import_job_id_on_images.py` | New migration: add `import_job_id` column + index to `images` |
| `backend/app/models/database.py` | Add `import_job_id` column to `Image` model |
| `backend/pipeline/maintenance.py` | Add `mark_interrupted_jobs()` function |
| `backend/app/main.py` | Call `mark_interrupted_jobs()` at startup |
| `backend/pipeline/ingestion.py` | Thread `import_job_id` through `_run_group` → `prepare_single_image` → `image_data` → `_save_image_to_db`; update `_finalize_import_job` for post-cancel sweep |
| `backend/app/services/import_state.py` | Add `broken` to terminal state guard |
| `backend/app/api/imports.py` | Enhance cancel endpoint with image cleanup logic |
| `frontend/src/components/ActivityDock.tsx` | Handle `broken` status, extend `canCancel`, add confirmation dialog |

---

## Verification

1. **Crash simulation**: start an import, kill the backend process, restart → verify stuck jobs appear as `broken` in ActivityDock within seconds of restart
2. **Cancel active import**: start a large import, cancel mid-flight → verify staging dir deleted, all imported images removed from search, Qdrant vectors removed
3. **Cancel duplicate import**: import a folder containing files already in the DB → cancel → verify the original pre-existing images are NOT deleted, only the duplicate rows
4. **Cancel broken import**: simulate crash scenario from (1), then cancel the broken job → full cleanup verified as in (2)
5. **Cancel staging import**: cancel before confirming any groups → staging deleted, no DB cleanup needed (no images yet), job cancelled
6. **Dismiss for failed**: verify old `failed` imports (non-interrupted) now show "Cancel & Remove" instead of silent dismiss
