# Import Pipeline Robustness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure every import job always reaches a truthful terminal state and ActivityDock is a faithful mirror of reality — no jobs silently disappear, get stuck, or show misleading status.

**Architecture:** Six targeted fixes to close gaps identified in the deep analysis. Backend gets a `/fail` endpoint for accurate error status, `staging` jobs are marked broken on restart, DB batch failures are isolated per-batch. Frontend gets auto-confirm retry with fallback to `/fail`, and ActivityDock becomes persistent and clickable for all states. Backend processes get crash supervision.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), SQLAlchemy (ORM), SQLite (DB)

**Design doc:** `docs/plans/2026-03-02-import-pipeline-robustness-design.md`

---

## Task 1: Backend `/fail` endpoint

**Files:**
- Modify: `backend/app/models/schemas.py:469-488` (ImportJobSummary + ActiveImportsResponse)
- Modify: `backend/app/api/imports.py` (add endpoint, update `/active` and `/status`)
- Test: `backend/tests/integration/test_imports_status.py`

**Step 1: Add `error_message` to `ImportJobSummary` schema**

In `backend/app/models/schemas.py:469-482`, add the field:

```python
class ImportJobSummary(BaseModel):
    """Lightweight summary for the active imports tray."""

    job_id: str
    source_label: str | None = None
    status: str
    error_message: str | None = None  # ← ADD THIS
    total_groups: int = 0
    completed_groups: int = 0
    failed_groups: int = 0
    running_groups: int = 0
    pending_groups: int = 0
    total_files: int = 0
    processed_files: int = 0
    created_at: datetime
```

**Step 2: Write failing tests for `/fail` endpoint**

Add to `backend/tests/integration/test_imports_status.py`:

```python
# ---------------------------------------------------------------------------
# POST /api/v1/imports/{job_id}/fail
# ---------------------------------------------------------------------------


class TestFailEndpoint:
    def test_fail_uploading_job(self, test_client, tmp_db):
        """Uploading job transitions to failed with error message."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_upload", status="uploading")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_upload/fail",
            json={"error_message": "Network timeout during upload"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "Network timeout during upload"

    def test_fail_staging_job(self, test_client, tmp_db):
        """Staging job transitions to failed with error message."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_staging", status="staging")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_staging/fail",
            json={"error_message": "Analysis failed: corrupt file"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_fail_active_job_rejected(self, test_client, tmp_db):
        """Active jobs cannot use /fail — they have running groups."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_active", status="active")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_active/fail",
            json={"error_message": "Should not work"},
        )
        assert resp.status_code == 409

    def test_fail_completed_job_rejected(self, test_client, tmp_db):
        """Terminal jobs cannot use /fail."""
        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_done", status="completed")
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/imports/job_fail_done/fail",
            json={"error_message": "Nope"},
        )
        assert resp.status_code == 409

    def test_fail_nonexistent_job(self, test_client):
        resp = test_client.post(
            "/api/v1/imports/nope/fail",
            json={"error_message": "Gone"},
        )
        assert resp.status_code == 404

    def test_fail_cleans_staging(self, test_client, tmp_db, tmp_path, monkeypatch):
        """Failing a job removes its staging directory."""
        from backend.app import config

        staging_root = tmp_path / "staging"
        staging_root.mkdir()
        monkeypatch.setattr(config.settings, "staging_dir", staging_root)

        _, SessionLocal = tmp_db
        db = SessionLocal()
        _make_job(db, "job_fail_cleanup", status="uploading")
        db.commit()
        db.close()

        # Create fake staging dir
        (staging_root / "job_fail_cleanup").mkdir()
        assert (staging_root / "job_fail_cleanup").exists()

        resp = test_client.post(
            "/api/v1/imports/job_fail_cleanup/fail",
            json={"error_message": "Upload broken"},
        )
        assert resp.status_code == 200
        assert not (staging_root / "job_fail_cleanup").exists()
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest backend/tests/integration/test_imports_status.py::TestFailEndpoint -v`
Expected: FAIL — endpoint doesn't exist yet.

**Step 4: Implement `/fail` endpoint**

Add to `backend/app/api/imports.py`, after the cancel endpoint (~line 1034). Add the request model at the top of the file with the other models:

```python
class FailImportRequest(BaseModel):
    error_message: str


@router.post("/{job_id}/fail")
async def fail_import(job_id: str, body: FailImportRequest, db: Session = Depends(get_db)):
    """Mark an import job as failed (upload/analyse error, not user cancellation).

    Only valid from 'uploading' or 'staging' states. For jobs with running groups,
    the pipeline itself handles failure via transition_job_status().
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    allowed_statuses = {"uploading", "staging"}
    if job.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot fail a job in '{job.status}' status (only uploading/staging)",
        )

    # Clean up staging directory
    staging_dir = settings.staging_dir / job_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)

    now = datetime.now(UTC).replace(tzinfo=None)
    job.status = "failed"
    job.error_message = body.error_message[:500] if body.error_message else None
    job.completed_at = now
    job.updated_at = now
    job.pending_groups = 0
    db.commit()

    return {
        "status": "failed",
        "error_message": job.error_message,
        "staging_cleaned": True,
    }
```

**Step 5: Populate `error_message` in `/active` response**

In `backend/app/api/imports.py`, in the `get_active_imports` function (~line 808), add `error_message` to the `ImportJobSummary` constructor:

```python
        summaries.append(
            ImportJobSummary(
                job_id=job.id,
                source_label=job.source_label,
                status=job.status,
                error_message=job.error_message,  # ← ADD THIS
                total_groups=job.pending_groups + len(groups),
                # ... rest unchanged
            )
        )
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest backend/tests/integration/test_imports_status.py::TestFailEndpoint -v`
Expected: All PASS.

**Step 7: Commit**

```bash
git add backend/app/api/imports.py backend/app/models/schemas.py backend/tests/integration/test_imports_status.py
git commit -m "feat: add /fail endpoint for accurate import error status"
```

---

## Task 2: Mark `staging` jobs as broken on restart

**Files:**
- Modify: `backend/pipeline/maintenance.py:294` (one line change)
- Modify: `backend/tests/unit/test_maintenance.py:266-269` (update existing test)

**Step 1: Update the existing test that asserts staging is unchanged**

In `backend/tests/unit/test_maintenance.py`, replace the test at line 266:

```python
    def test_staging_job_becomes_broken(self, db_session):
        _make_import_job(db_session, "j1", "staging")
        mark_interrupted_jobs(db_session)
        db_session.commit()
        assert db_session.query(ImportJob).filter_by(id="j1").first().status == "broken"
```

Also update `test_no_interrupted_jobs_returns_zero` at line 295 — it currently includes a `staging` job and expects count=0. Change it:

```python
    def test_no_interrupted_jobs_returns_zero(self, db_session):
        _make_import_job(db_session, "j1", "completed")
        _make_import_job(db_session, "j2", "awaiting_input")
        count = mark_interrupted_jobs(db_session)
        assert count == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/unit/test_maintenance.py::TestMarkInterruptedJobs -v`
Expected: `test_staging_job_becomes_broken` FAILS (staging currently unchanged), `test_no_interrupted_jobs_returns_zero` may also fail.

**Step 3: Add `staging` to interrupted statuses**

In `backend/pipeline/maintenance.py:294`, change:

```python
        interrupted_statuses = ("uploading", "staging", "active")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/unit/test_maintenance.py::TestMarkInterruptedJobs -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/pipeline/maintenance.py backend/tests/unit/test_maintenance.py
git commit -m "fix: mark staging jobs as broken on server restart"
```

---

## Task 3: DB batch failure isolation

**Files:**
- Modify: `backend/pipeline/ingestion.py:714-727` (`_process_batch`)
- Test: `backend/tests/unit/test_batch_isolation.py` (new file)

**Step 1: Write failing test**

Create `backend/tests/unit/test_batch_isolation.py`:

```python
"""Unit test for DB batch failure isolation in _process_batch.

Verifies that a batch_save_to_database failure marks images as failed
but does not raise, so _run_group can continue to the next batch.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.ingestion import _process_batch


def _make_prepared_result(filename: str, status: str = "success") -> dict:
    """Create a minimal prepared result dict for _process_batch."""
    result = {
        "status": status,
        "original_image_path": f"/staging/{filename}",
        "image_data": {
            "name": filename,
            "filename": filename,
            "author": "Test",
            "storage_key": f"key_{filename}",
            "needs_review": True,
        },
        "qdrant_metadata": {"author": "Test"},
        "embedding": [0.1] * 512,
    }
    return result


class TestProcessBatchDbIsolation:
    @patch("backend.pipeline.ingestion.batch_save_to_qdrant")
    @patch("backend.pipeline.ingestion.batch_save_to_database")
    @patch("backend.pipeline.ingestion.batch_generate_clip_embeddings")
    def test_db_failure_marks_images_failed_not_raises(
        self, mock_clip, mock_db_save, mock_qdrant_save
    ):
        """When batch_save_to_database throws, images are marked failed but no exception propagates."""
        prepared = [_make_prepared_result("a.jpg"), _make_prepared_result("b.jpg")]

        # CLIP succeeds
        mock_clip.return_value = [[0.1] * 512, [0.2] * 512]
        # DB save throws
        mock_db_save.side_effect = Exception("disk full")

        # Should NOT raise
        results, batch_failed = _process_batch(prepared)

        assert batch_failed == 2
        assert all(r["status"] == "failed" for r in results)
        assert all("db_save" in r.get("error_info", {}).get("stage", "") for r in results)
        # Qdrant should NOT be called when DB save failed
        mock_qdrant_save.assert_not_called()

    @patch("backend.pipeline.ingestion.batch_save_to_qdrant")
    @patch("backend.pipeline.ingestion.batch_save_to_database")
    @patch("backend.pipeline.ingestion.batch_generate_clip_embeddings")
    def test_db_success_proceeds_normally(self, mock_clip, mock_db_save, mock_qdrant_save):
        """Normal path: DB save succeeds, Qdrant save is called."""
        prepared = [_make_prepared_result("a.jpg")]

        mock_clip.return_value = [[0.1] * 512]
        mock_db_save.return_value = [42]  # image IDs

        results, batch_failed = _process_batch(prepared)

        assert batch_failed == 0
        assert results[0]["status"] == "success"
        mock_qdrant_save.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/unit/test_batch_isolation.py -v`
Expected: `test_db_failure_marks_images_failed_not_raises` FAILS (exception propagates).

**Step 3: Wrap `batch_save_to_database` in `_process_batch`**

In `backend/pipeline/ingestion.py`, replace lines 714-727 (the DB save + Qdrant save section):

```python
    # Re-filter to only truly successful results
    all_successful = [r for r in successful if r["status"] == "success"]

    # Batch DB save — isolated so a failure doesn't kill subsequent batches
    image_ids: list[int] = []
    if all_successful:
        image_data_list = [r["image_data"] for r in all_successful]
        try:
            image_ids = batch_save_to_database(image_data_list)
        except Exception as db_exc:
            logger.exception("Batch DB save failed for %d images", len(all_successful))
            error_info = classify_ingest_error(db_exc, stage="db_save")
            for prep in all_successful:
                prep["status"] = "failed"
                prep["error"] = error_info["reason"]
                prep["error_info"] = error_info
                batch_failed += 1
            all_successful = []

    # Batch Qdrant save (only if DB save succeeded)
    if all_successful and image_ids:
        qdrant_items = [
            {
                "image_id": image_id,
                "embedding": prep["embedding"],
                "metadata": prep["qdrant_metadata"],
            }
            for image_id, prep in zip(image_ids, all_successful, strict=True)
        ]
        batch_save_to_qdrant(qdrant_items)

        # Attach image IDs to results
        for prep, image_id in zip(all_successful, image_ids, strict=True):
            prep["image_id"] = image_id

    return prepared_results, batch_failed
```

Also add `classify_ingest_error` to the imports at the top of the file if not already imported in scope (it is — used in `prepare_single_image`).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/unit/test_batch_isolation.py -v`
Expected: All PASS.

Run: `uv run pytest backend/tests/ -v --timeout=60`
Expected: All existing tests still pass.

**Step 5: Commit**

```bash
git add backend/pipeline/ingestion.py backend/tests/unit/test_batch_isolation.py
git commit -m "fix: isolate DB batch failures so they don't kill entire group"
```

---

## Task 4: Frontend `/fail` API + upload error handler

**Files:**
- Modify: `frontend/src/lib/api.ts:218-320` (importApi)
- Modify: `frontend/src/hooks/useImportUpload.ts:281-289` (error handler)

**Step 1: Add `importApi.fail` method**

In `frontend/src/lib/api.ts`, add after the `cancel` method inside `importApi`:

```typescript
  fail: async (jobId: string, errorMessage: string): Promise<void> => {
    await api.post(`/imports/${jobId}/fail`, { error_message: errorMessage })
  },
```

**Step 2: Update upload error handler**

In `frontend/src/hooks/useImportUpload.ts`, replace lines 281-289:

```typescript
      } catch (err) {
        // Mark job as failed (not cancelled) to preserve error context on the backend.
        // Fall back to cancel if /fail isn't available (shouldn't happen).
        const errorMessage = getApiErrorMessage(err, 'Upload failed')
        if (jobIdForCancel) {
          try {
            await importApi.fail(jobIdForCancel, errorMessage)
          } catch {
            importApi.cancel(jobIdForCancel).catch(() => {})
          }
          removeImportState(jobIdForCancel)
        }
        setUploadError(errorMessage)
      }
```

**Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/useImportUpload.ts
git commit -m "feat: call /fail instead of /cancel on upload errors"
```

---

## Task 5: Auto-confirm retry with fallback

**Files:**
- Modify: `frontend/src/hooks/useImportState.ts:442-497`

**Step 1: Add retry logic to `handleConfirmAll`**

Replace the catch block at line 476 (inside `handleConfirmAll`):

```typescript
    } catch (err) {
      // Retry with exponential backoff before giving up
      const delays = [1000, 2000, 4000]
      let succeeded = false
      for (const delay of delays) {
        await new Promise((resolve) => setTimeout(resolve, delay))
        try {
          const response = await importApi.confirmAll(
            jobId,
            toSubmit.map(({ author, group_name, files }) => ({ author, group_name, files })),
          )
          for (const { i, group_name } of toSubmit) {
            const matchedGroup = response.groups.find((gs) => gs.group_name === group_name)
            if (matchedGroup?.group_job_id) {
              updateGroup(i, { group_job_id: matchedGroup.group_job_id })
            }
          }
          setTimeout(saveNow, 100)
          succeeded = true
          break
        } catch {
          // Continue to next retry
        }
      }
      if (!succeeded) {
        // All retries failed — mark job as failed on backend
        const errorMessage = getApiErrorMessage(err, 'Failed to start processing')
        try {
          await importApi.fail(jobId, errorMessage)
        } catch {
          // Best effort
        }
        toSubmit.forEach(({ i }) => updateGroup(i, { status: 'failed' }))
        setState('done')
      }
    }
```

Note: `getApiErrorMessage` will need to be imported. Check if it's already available — it's used in `useImportUpload.ts`. Add the import at the top of `useImportState.ts`:

```typescript
import { getApiErrorMessage } from '@/lib/api'
```

If `getApiErrorMessage` is not exported from `@/lib/api`, check where it's defined and import from there.

**Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/hooks/useImportState.ts
git commit -m "fix: auto-retry confirm-all with fallback to /fail"
```

---

## Task 6: ActivityDock — persistent unreviewed jobs

**Files:**
- Modify: `backend/app/api/imports.py:774-820` (`get_active_imports`)
- Test: Add to `backend/tests/integration/test_imports_status.py`

**Step 1: Write failing test**

Add to `backend/tests/integration/test_imports_status.py`:

```python
class TestActiveImportsUnreviewed:
    def test_old_completed_job_with_unreviewed_images_still_active(self, test_client, tmp_db):
        """Completed jobs with needs_review images persist past the 1-hour TTL."""
        _, SessionLocal = tmp_db
        db = SessionLocal()

        # Create a completed job from 2 hours ago
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        job = _make_job(db, "job_old_unreviewed", status="completed", total_files=1)
        job.completed_at = old_time
        gj = _make_group_job(
            db, "job_old_unreviewed", "grp_unreviewed",
            status="completed", processed=1, total=1, completed_at=old_time,
        )

        # Create an image with needs_review=True linked to this job
        group = ImageGroup(base_name="UnreviewedGroup", author="Test")
        db.add(group)
        db.flush()
        gj.created_group_id = group.id
        img = Image(
            name="test",
            filename="test.jpg",
            author="Test",
            storage_key="key.jpg",
            group_id=group.id,
            needs_review=True,
            import_job_id="job_old_unreviewed",
            media_type="image",
        )
        db.add(img)
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/active")
        assert resp.status_code == 200
        job_ids = [j["job_id"] for j in resp.json()["jobs"]]
        assert "job_old_unreviewed" in job_ids

    def test_old_completed_job_without_unreviewed_not_active(self, test_client, tmp_db):
        """Completed jobs where all images are reviewed are filtered out after 1 hour."""
        _, SessionLocal = tmp_db
        db = SessionLocal()

        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        job = _make_job(db, "job_old_reviewed", status="completed", total_files=1)
        job.completed_at = old_time
        db.commit()
        db.close()

        resp = test_client.get("/api/v1/imports/active")
        job_ids = [j["job_id"] for j in resp.json()["jobs"]]
        assert "job_old_reviewed" not in job_ids
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/integration/test_imports_status.py::TestActiveImportsUnreviewed -v`
Expected: `test_old_completed_job_with_unreviewed_images_still_active` FAILS.

**Step 3: Update `/active` endpoint**

In `backend/app/api/imports.py`, modify the `get_active_imports` function. Replace the terminal job filtering logic (~line 793-796):

```python
        truly_terminal = {"completed", "failed", "cancelled", "expired"}
        if job.status in truly_terminal:
            if job.status == "completed":
                # Completed jobs with unreviewed images persist indefinitely
                has_unreviewed = (
                    db.query(Image)
                    .filter(Image.import_job_id == job.id, Image.needs_review == True)  # noqa: E712
                    .limit(1)
                    .count()
                    > 0
                )
                if has_unreviewed:
                    pass  # Keep this job in the active list
                elif job.completed_at is None or job.completed_at < cutoff:
                    continue
            else:
                if job.completed_at is None or job.completed_at < cutoff:
                    continue
```

Add `Image` to imports at top of file if not already present.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/integration/test_imports_status.py::TestActiveImportsUnreviewed -v`
Expected: All PASS.

Run: `uv run pytest backend/tests/integration/test_imports_status.py -v`
Expected: All existing tests still pass.

**Step 5: Commit**

```bash
git add backend/app/api/imports.py backend/tests/integration/test_imports_status.py
git commit -m "feat: keep completed-unreviewed imports in active list indefinitely"
```

---

## Task 7: ActivityDock — pass error_message + file_errors through

**Files:**
- Modify: `frontend/src/hooks/useActiveImports.ts:25-49,188-203`
- Modify: `frontend/src/lib/api.ts` (types)

**Step 1: Add fields to `ActiveImportJob` type**

In `frontend/src/hooks/useActiveImports.ts`, add to the interface at line ~48:

```typescript
  /** Backend error message for failed/broken jobs. */
  errorMessage?: string
  /** Per-image file errors from processing. */
  fileErrors?: Array<{ filename: string; reason: string; stage: string }>
```

**Step 2: Update `backendToActiveJob` mapping**

In the `backendToActiveJob` function (~line 188-203), add:

```typescript
    errorMessage: summary.error_message ?? undefined,
```

**Step 3: Update the `ImportJobSummary` type in api.ts**

Find the `ImportJobSummary` interface/type in `frontend/src/lib/api.ts` (or wherever it's typed) and add:

```typescript
  error_message?: string | null
```

**Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 5: Commit**

```bash
git add frontend/src/hooks/useActiveImports.ts frontend/src/lib/api.ts
git commit -m "feat: pass error_message through to ActiveImportJob"
```

---

## Task 8: ActivityDock — always-visible cancel on failed/broken + clickable

**Files:**
- Modify: `frontend/src/components/ActivityDock.tsx:317-327`
- Modify: `frontend/src/components/Gallery.tsx:264-289`

**Step 1: Make cancel always visible on failed/broken**

In `frontend/src/components/ActivityDock.tsx`, the cancel button at line 317 has class `opacity-0 group-hover/job:opacity-100`. Add a condition for failed/broken:

```typescript
          {canCancel && !confirmingCancel && (
            <button
              onClick={handleCancelClick}
              className={`shrink-0
                h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/30 hover:text-destructive hover:bg-destructive/10 transition-all
                ${job.status === 'failed' || job.status === 'broken' ? '' : 'opacity-0 group-hover/job:opacity-100'}`}
              title="Cancel"
            >
              <X className="h-3 w-3" />
            </button>
          )}
```

**Step 2: Add failed/broken click handler in Gallery.tsx**

In `frontend/src/components/Gallery.tsx`, in the `onOpenJob` handler (~line 264), add a branch for failed/broken before the closing of the handler:

```typescript
        onOpenJob={(jobId) => {
          const job = activeImports.jobs.find((j) => j.jobId === jobId)
          if (job?.status === 'completed' && job.pendingGroups === 0) {
            // ... existing completed handler ...
          } else if (job?.status === 'failed' || job?.status === 'broken') {
            // Open summary dialog for failed/broken jobs
            dialogs.setImportSummaryJobId(jobId)
          } else if (
            // ... existing resumable handler ...
          ) {
            dialogs.openImportDialog(jobId)
          }
        }}
```

Note: `dialogs.setImportSummaryJobId` will be wired up in Task 9 when we create ImportSummaryDialog. For now, add the state to the dialogs hook — find where dialog state is managed and add:

```typescript
const [importSummaryJobId, setImportSummaryJobId] = useState<string | null>(null)
```

**Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors (may have unused variable warning for `setImportSummaryJobId` — fine for now).

**Step 4: Commit**

```bash
git add frontend/src/components/ActivityDock.tsx frontend/src/components/Gallery.tsx
git commit -m "feat: always-visible cancel on failed/broken, add click handler"
```

---

## Task 9: ImportSummaryDialog

**Files:**
- Create: `frontend/src/components/ImportSummaryDialog.tsx`
- Modify: `frontend/src/components/Gallery.tsx` (wire up)

**Step 1: Create the dialog component**

Use the `frontend-design` skill to create `ImportSummaryDialog.tsx`. The dialog should:

- Accept props: `jobId: string | null`, `open: boolean`, `onClose: () => void`, `onCancel: (jobId: string) => void`
- On open, fetch `importApi.status(jobId)` to get group details + file errors
- Display: status badge, error message (if any), group table (name, status, processed/failed counts), per-image errors grouped by reason
- "Cancel & Clean Up" button that calls `onCancel(jobId)` then closes
- "Close" button
- Use existing dialog primitives from `@/components/ui/dialog`
- Match the visual language of existing dialogs (dark theme, muted colors, etc.)

**Step 2: Wire up in Gallery.tsx**

Render the dialog alongside other dialogs, gated on `importSummaryJobId`:

```typescript
<ImportSummaryDialog
  jobId={dialogs.importSummaryJobId}
  open={dialogs.importSummaryJobId !== null}
  onClose={() => dialogs.setImportSummaryJobId(null)}
  onCancel={(jobId) => {
    activeImports.cancelJob(jobId)
    dialogs.setImportSummaryJobId(null)
  }}
/>
```

**Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 4: Commit**

```bash
git add frontend/src/components/ImportSummaryDialog.tsx frontend/src/components/Gallery.tsx
git commit -m "feat: add ImportSummaryDialog for failed/broken jobs"
```

---

## Task 10: Poll failure indicator

**Files:**
- Modify: `frontend/src/hooks/useImportPolling.ts:32-67`
- Modify: `frontend/src/components/ActivityDock.tsx`

**Step 1: Add consecutive failure tracking to useImportPolling**

The hook currently returns `void`. Change it to return a `connectionLost` flag. Update the hook:

```typescript
interface UseImportPollingResult {
  connectionLost: boolean
}

export function useImportPolling({
  state,
  jobId,
  setGroups,
  setState,
}: UseImportPollingOptions): UseImportPollingResult {
  const consecutiveFailuresRef = useRef(0)
  const [connectionLost, setConnectionLost] = useState(false)
```

In the poll function's catch block (line 65-67), replace:

```typescript
      } catch {
        consecutiveFailuresRef.current += 1
        if (consecutiveFailuresRef.current >= 3) {
          setConnectionLost(true)
        }
      }
```

In the success path (after updating groups), add:

```typescript
        consecutiveFailuresRef.current = 0
        setConnectionLost(false)
```

Return the result:

```typescript
  return { connectionLost }
```

**Step 2: Update callers of useImportPolling**

In `useImportState.ts`, update to capture the return value and expose it:

```typescript
const { connectionLost } = useImportPolling({ state, jobId, setGroups, setState })
```

Pass `connectionLost` through to wherever the ImportDialog can display it.

**Step 3: Show indicator in ActivityDock**

In `ActivityDock.tsx`, when rendering active import job cards, if the job has `connectionLost: true`, add a subtle indicator:

```typescript
{job.connectionLost && (
  <span className="text-[10px] text-amber-500/70">Connection lost</span>
)}
```

Note: This requires `connectionLost` to flow through to `ActiveImportJob`. Since the polling hook runs inside `useImportState` (dialog-scoped), it only applies when the dialog is open. For the ActivityDock, the `useActiveImports` hook has its own polling — add similar failure tracking there.

**Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 5: Commit**

```bash
git add frontend/src/hooks/useImportPolling.ts frontend/src/hooks/useImportState.ts frontend/src/components/ActivityDock.tsx frontend/src/hooks/useActiveImports.ts
git commit -m "feat: show connection lost indicator after 3 poll failures"
```

---

## Task 11: Backend auto-restart — `scripts/start.py`

**Files:**
- Modify: `scripts/start.py`

**Step 1: Replace fire-and-forget with supervision loop**

Rewrite `scripts/start.py`:

```python
"""Start the Scene Atlas backend server with crash supervision.

Launches the FastAPI server as a supervised child process. If the server
crashes, it is automatically restarted with exponential backoff. Gives up
after 10 crashes within 5 minutes to avoid infinite crash loops.

The frontend dev server must be started separately in a second terminal:
  cd frontend && npm run dev

PIDs are written to .pids/ so stop.py can terminate the process cleanly.

Usage:
  uv run python scripts/start.py
"""

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
PIDS_DIR = ROOT / ".pids"
LOGS_DIR = ROOT / "logs"
PYTHON = sys.executable

MAX_RESTARTS = 10
WINDOW_SECS = 300
MAX_BACKOFF = 30


def _supervise(name: str, cmd: list[str]) -> None:
    """Launch and supervise a child process with auto-restart on crash."""
    LOGS_DIR.mkdir(exist_ok=True)
    PIDS_DIR.mkdir(exist_ok=True)

    restarts: list[float] = []
    backoff = 1

    # Forward SIGTERM/SIGINT to child
    child_proc = None

    def _forward_signal(sig, _frame):
        if child_proc and child_proc.poll() is None:
            child_proc.send_signal(sig)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    while True:
        log_path = LOGS_DIR / f"{name}.log"
        log_file = open(log_path, "a")

        extra = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        child_proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **extra,
        )
        pid_file = PIDS_DIR / f"{name}.pid"
        pid_file.write_text(str(child_proc.pid))
        print(f"  [{name}] PID {child_proc.pid}")

        exit_code = child_proc.wait()
        log_file.close()

        if exit_code == 0:
            print(f"  [{name}] exited cleanly")
            break

        # Check crash window
        now = time.time()
        restarts = [t for t in restarts if now - t < WINDOW_SECS]

        if len(restarts) >= MAX_RESTARTS:
            print(f"  [{name}] crashed {MAX_RESTARTS} times in {WINDOW_SECS}s — giving up")
            sys.exit(1)

        restarts.append(now)
        print(f"  [{name}] exited with code {exit_code}, restarting in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)


def main() -> None:
    print("=" * 50)
    print("  Scene Atlas — Starting (supervised)")
    print("=" * 50)
    print()

    print("Starting FastAPI server...")
    _supervise(
        "api",
        [PYTHON, "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )


if __name__ == "__main__":
    main()
```

**Step 2: Verify it works**

Run: `uv run python scripts/start.py` (manually verify it starts, then Ctrl-C to stop)

**Step 3: Commit**

```bash
git add scripts/start.py
git commit -m "feat: add crash supervision to start.py"
```

---

## Task 12: Backend auto-restart — `entry.py` (Electron)

**Files:**
- Modify: `backend/pyinstaller/entry.py`

**Step 1: Add restart loop to entry.py**

```python
"""PyInstaller entry point for Scene Atlas backend sidecar.

Sets environment variables BEFORE importing any backend.app modules,
because importing config.py immediately constructs Settings() and
computes all derived paths from data_dir.

Includes crash supervision: if uvicorn crashes, it restarts with
exponential backoff. Gives up after 10 crashes in 5 minutes.
"""

import argparse
import logging
import os
import sys
import time

MAX_RESTARTS = 10
WINDOW_SECS = 300
MAX_BACKOFF = 30


def main():
    parser = argparse.ArgumentParser(description="Scene Atlas backend (packaged)")
    parser.add_argument("--port", type=int, required=True, help="Port to bind to")
    parser.add_argument("--data-dir", type=str, required=True, help="Data directory path")
    args = parser.parse_args()

    # Must set env vars before any backend.app import triggers Settings()
    os.environ["DATA_DIR"] = args.data_dir
    os.environ["API_PORT"] = str(args.port)
    os.environ["API_HOST"] = "127.0.0.1"
    os.environ["APP_MODE"] = "app"

    from pathlib import Path

    from backend.app.logging_config import setup_logging

    setup_logging(Path(args.data_dir))

    logger = logging.getLogger(__name__)

    import uvicorn

    from backend.app.main import app

    restarts: list[float] = []
    backoff = 1

    while True:
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port)
            break  # Clean exit (e.g. graceful shutdown)
        except SystemExit:
            break  # Intentional exit
        except Exception:
            now = time.time()
            restarts = [t for t in restarts if now - t < WINDOW_SECS]

            if len(restarts) >= MAX_RESTARTS:
                logger.critical(
                    "Backend crashed %d times in %ds — giving up",
                    MAX_RESTARTS,
                    WINDOW_SECS,
                )
                sys.exit(1)

            restarts.append(now)
            logger.error(
                "Backend crashed, restarting in %ds (crash %d/%d in window)",
                backoff,
                len(restarts),
                MAX_RESTARTS,
                exc_info=True,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add backend/pyinstaller/entry.py
git commit -m "feat: add crash supervision to Electron backend entry"
```

---

## Task 13: Update design docs + final verification

**Files:**
- Modify: `design/import-state-machine.md`
- Modify: `design/web-import.md`
- Delete or mark done: `design/upload-error-improvements-todo.md`

**Step 1: Update import-state-machine.md**

Add note about `/fail` endpoint and `staging` → `broken` on restart.

**Step 2: Update web-import.md**

Add note about auto-confirm retry, `/fail` on errors, persistent unreviewed jobs.

**Step 3: Mark upload-error-improvements-todo.md as completed**

Items 1 (fail endpoint) and 3 (error_message in summary) are now done. Item 2 (filename in analyse errors) is deferred.

**Step 4: Run full test suite**

Run: `uv run pytest -v --timeout=120`
Expected: All tests pass.

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 5: Final commit**

```bash
git add design/
git commit -m "docs: update design docs for import pipeline robustness"
```
