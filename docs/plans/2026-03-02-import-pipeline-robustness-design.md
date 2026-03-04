# Import Pipeline Robustness — Design

## Context

Deep analysis of the import flow revealed that while the happy path is solid, several failure modes can leave jobs in limbo: stuck in `staging`, silently disappearing from the ActivityDock, showing misleading status text, or losing error context. The core invariant we're enforcing:

> **Every import job MUST reach a truthful terminal state (completed, failed, cancelled). ActivityDock MUST faithfully represent reality at all times. No job should ever silently disappear, get stuck, or show a misleading status.**

Resumption of interrupted jobs is explicitly out of scope (future feature).

---

## Workstream 1: `/fail` endpoint + accurate error status

**Problem:** Upload/analyse errors call `/cancel`, which is semantically wrong ("user chose to stop" vs "something broke") and loses error context on the backend.

**Changes:**

`backend/app/api/imports.py` — add `POST /imports/{job_id}/fail`:
- Accepts `{ error_message: string }`
- Guard: only from `uploading` or `staging` status
- Sets `status = "failed"`, `error_message = error_message`, `completed_at = now()`
- Cleans staging directory (same as cancel)
- Returns 200 with updated job status

`backend/app/services/import_state.py` — add `"failed"` as valid transition from `uploading`/`staging` in docstring (the `/fail` endpoint sets it directly, not via `transition_job_status()`, since there are no group jobs to evaluate).

`backend/app/schemas/imports.py` — add `error_message: str | None` to `ImportJobSummary`.

`backend/app/api/imports.py` — populate `error_message` in `/imports/active` and `/imports/{id}/status` responses.

`frontend/src/lib/api.ts` — add `importApi.fail(jobId, errorMessage)`.

`frontend/src/hooks/useImportUpload.ts` — in the error handler, call `importApi.fail()` instead of `importApi.cancel()`. Stop storing error in localStorage (it's on the backend now).

`frontend/src/hooks/useActiveImports.ts` — pass `errorMessage` through from backend response to `ActiveImportJob`.

---

## Workstream 2: Auto-confirm retry

**Problem:** If `POST /confirm-all` fails after analysis, the auto-confirm useEffect won't re-fire (it only triggers on `'preview'` state transition). Job stuck in `staging` forever.

**Changes:**

`frontend/src/hooks/useImportState.ts` — wrap the auto-confirm `handleConfirmAll` call:
- On failure, retry up to 3 times with exponential backoff (1s, 2s, 4s)
- If all retries fail, call `importApi.fail(jobId, errorMessage)` to mark the job as failed
- Set dialog state to `'done'` so the dialog shows the failure
- Job always reaches a terminal state

---

## Workstream 3: Backend restart — mark `staging` as broken

**Problem:** `mark_interrupted_jobs()` only covers `uploading` and `active`. A job in `staging` (analysis done, waiting for confirm) has no frontend to confirm it after a restart, so it sits until 48h expiry.

**Changes:**

`backend/pipeline/maintenance.py` — in `mark_interrupted_jobs()`:
- Add `"staging"` to `interrupted_statuses` tuple: `("uploading", "staging", "active")`
- These get marked `broken` with the existing error message

---

## Workstream 4: Per-image resilience (DB batch isolation)

**Problem:** If `batch_save_to_database` throws (e.g. disk full, constraint violation), it propagates to `_run_group`'s outer catch, which marks the **entire group** as failed and skips all remaining batches. Already-processed batches are fine, but the current + future batches are lost.

**Changes:**

`backend/pipeline/ingestion.py` — in `_process_batch()`:
- Wrap `batch_save_to_database(image_data_list)` in try/except
- On failure: mark all images in `all_successful` as failed with `stage="db_save"`, using `classify_ingest_error()`
- Increment `batch_failed` count
- Clear `all_successful` so the Qdrant save is skipped (no image IDs to save)
- **Return** normally instead of raising — `_run_group` continues to next batch

This mirrors how CLIP batch failure already works (lines 671-678): mark images as failed, continue.

---

## Workstream 5: ActivityDock truthfulness

### 5a: Completed-unreviewed jobs persist indefinitely

**Problem:** Completed jobs disappear from `/imports/active` after 1 hour. If the user hasn't reviewed, the images become unfindable (`needs_review=True`, hidden from gallery).

`backend/app/api/imports.py` — in the `/imports/active` endpoint:
- Current: includes completed jobs with `completed_at` within 1 hour
- Change: also include completed jobs where any Image in the import still has `needs_review=True`
- Query: join through `ImportGroupJob.created_group_id` → `ImageGroup` → `Image` where `needs_review=True`, or simpler: check if any `Image` with `import_job_id = job.id` has `needs_review=True`

### 5b: Failed/broken jobs are clickable

**Problem:** Clicking failed/broken jobs in ActivityDock does nothing.

`frontend/src/components/Gallery.tsx` — in `onOpenJob`:
- Add branch for `failed`/`broken` status → open a new `ImportSummaryDialog`

`frontend/src/components/ImportSummaryDialog.tsx` (new file):
- Shows: job status, error message (from backend), group-level results (processed/failed counts), per-image `file_errors` list, and Cancel/Cleanup button
- Cancel button calls `importApi.cancel()` then dismisses the job
- Uses existing design language (card styling, status icons from ActivityDock)

### 5c: Surface per-image `file_errors`

`frontend/src/hooks/useActiveImports.ts` — pass `file_errors` from the status response through to `ActiveImportJob` type.

`frontend/src/components/ImportSummaryDialog.tsx` — render file errors grouped by reason, showing filename and stage.

### 5d: Always-visible cancel on failed/broken

`frontend/src/components/ActivityDock.tsx` — in `ImportJobCard`:
- For `failed` and `broken` status, render the cancel button without the `opacity-0 group-hover/job:opacity-100` classes

### 5e: Poll failure indicator

`frontend/src/hooks/useImportPolling.ts`:
- Add `consecutiveFailures` counter ref
- Increment on poll error, reset to 0 on success
- After 3 consecutive failures, set a `connectionLost: boolean` flag on the polling state
- Reset flag on success

`frontend/src/components/ActivityDock.tsx`:
- When `connectionLost` is true on an active job, show a subtle wifi-off icon and "Connection lost" subtext

---

## Workstream 6: Backend auto-restart

**Problem:** If the backend crashes, it stays dead. No supervisor restarts it.

### 6a: `scripts/start.py` (server mode)

Replace fire-and-forget `Popen` with a supervision loop:
```python
def _supervise(name, cmd, max_restarts=10, window_secs=300):
    restarts = []
    backoff = 1
    while True:
        proc = Popen(cmd, ...)
        proc.wait()

        # Clean old restart timestamps
        now = time.time()
        restarts = [t for t in restarts if now - t < window_secs]

        if len(restarts) >= max_restarts:
            log(f"{name} crashed too many times, giving up")
            sys.exit(1)

        restarts.append(now)
        log(f"{name} exited with code {proc.returncode}, restarting in {backoff}s")
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)
```

### 6b: `backend/pyinstaller/entry.py` (Electron mode)

Wrap `uvicorn.run()` in a similar retry loop:
```python
def main():
    # ... arg parsing, env setup ...
    restarts = []
    backoff = 1
    while True:
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port)
            break  # clean exit
        except Exception:
            # same restart logic as start.py
```

Exit with error code on too many crashes so Electron can show a fatal dialog.

### 6c: Dev mode

No code change. Devs use `uvicorn --reload` which handles restarts. Add a note to CLAUDE.md dev instructions.

---

## Files Modified (summary)

| File | Workstreams |
|------|-------------|
| `backend/app/api/imports.py` | 1, 5a |
| `backend/app/services/import_state.py` | 1 (docstring) |
| `backend/app/schemas/imports.py` | 1 |
| `backend/pipeline/ingestion.py` | 4 |
| `backend/pipeline/maintenance.py` | 3 |
| `scripts/start.py` | 6a |
| `backend/pyinstaller/entry.py` | 6b |
| `frontend/src/lib/api.ts` | 1, 2 |
| `frontend/src/hooks/useImportUpload.ts` | 1 |
| `frontend/src/hooks/useImportState.ts` | 2 |
| `frontend/src/hooks/useImportPolling.ts` | 5e |
| `frontend/src/hooks/useActiveImports.ts` | 1, 5c |
| `frontend/src/components/Gallery.tsx` | 5b |
| `frontend/src/components/ImportSummaryDialog.tsx` | 5b, 5c (new) |
| `frontend/src/components/ActivityDock.tsx` | 5d, 5e |

---

## Verification

1. **Unit tests:** Add tests for `/fail` endpoint (status guard, staging cleanup, error_message storage). Add test for `mark_interrupted_jobs` covering `staging` status. Add test for `_process_batch` DB failure isolation.
2. **Integration test:** Upload files → kill backend mid-processing → restart → verify jobs marked `broken` → verify ActivityDock shows them → verify cancel cleans up.
3. **Manual test:** Upload a batch with one corrupt file → verify group completes with per-image errors → verify errors visible in ImportSummaryDialog.
4. **Manual test:** Upload files → disconnect network before confirm-all → verify retry fires 3× → verify job marked failed → verify error shown in ActivityDock.
5. **Manual test:** Complete an import → don't review → wait >1 hour → verify job still in ActivityDock.
6. **Manual test:** Kill backend process → verify it auto-restarts → verify `mark_interrupted_jobs` runs on startup.
