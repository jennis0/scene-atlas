# Upload Error Handling — Backend Improvement Todo

These are the backend-side improvements deferred from the 2026-03-02 import UX bugfix
(Approach B items). The frontend fixes were applied as Approach A; these remain as follow-up.

**Status as of 2026-03-02 (import pipeline robustness pass):** Items 1 and 3 are complete.
Item 2 remains pending.

## Context

When the backend `analyse` or upload pipeline fails, we currently cancel the import job and
surface errors only in the ImportDialog. Approach A keeps the job visible in the ActivityDock
(via localStorage), but the error status and message are frontend-only and ephemeral.

---

## 1. Add `/imports/{job_id}/fail` endpoint — DONE

**Goal:** Let the frontend mark a job as `failed` (not `cancelled`) when an error occurs during
the upload/analysis phase. This is semantically more accurate — the user did not request
cancellation; the job failed.

**What it does:**
- Accepts `{ error_message: string }` body
- Sets `ImportJob.status = "failed"`, `ImportJob.error_message = error_message`,
  `ImportJob.completed_at = now()`
- Guard: only transitions from `staging` / `uploading` states (not from `active` or terminal)

**Completed:** Endpoint added in `backend/app/api/imports.py`. Frontend updated in
`useImportUpload.ts` to call `importApi.fail()` instead of `importApi.cancel()`, with a
`cancel()` fallback if `/fail` is unavailable. `error_message` no longer stored in
localStorage — it lives on the backend job record.

Also includes: `mark_interrupted_jobs()` at server startup marks `uploading`/`staging`/`active`
jobs as `broken` (same visual treatment as `failed`).

---

## 2. Include filename in analyse-step error responses — PENDING

**Goal:** When a specific file causes the backend `analyse` step to fail, the error response
should name the file so the user knows what to fix.

**Current behaviour:** `analyse()` throws a generic 500 error with no file context.

**What to do:**
- In `backend/pipeline/ingestion.py` (or wherever analyse catches per-file errors), catch
  per-file exceptions and re-raise with the filename included:
  e.g. `raise ValueError(f"Failed to analyse '{filename}': {original_error}")`
- The `analyse` API route should map this to a 422 with `detail` containing the filename.

**Files:**
- `backend/pipeline/staging.py` or `backend/pipeline/ingestion.py` — wrap per-file errors
- `backend/app/api/imports.py` — format error response with file detail

---

## 3. Expose `error_message` from `ImportJobSummary` — DONE

**Goal:** Once jobs can carry server-side error messages (from item 1 above), surface them in
the ActivityDock's `ImportJobCard` via the backend polling response.

**Completed:** `error_message: str | None` added to `ImportJobSummary` schema and populated
from `ImportJob.error_message` in `/imports/active` and `/imports/{id}` endpoints.
`useActiveImports` passes `errorMessage` through to `ActiveImportJob`. `ImportSummaryDialog`
(new component) renders the error message for `failed` and `broken` status jobs, accessible
from the ActivityDock cancel/review button.

---

## Priority

| Item | Effort | Impact | Status |
|------|--------|--------|--------|
| 1. `/fail` endpoint | Medium (backend + frontend) | High — accurate job status | Done |
| 2. Filename in analyse errors | Low–Medium | Medium — better error messages | Pending |
| 3. `error_message` in summary | Low | Medium — visible in ActivityDock without localStorage | Done |
