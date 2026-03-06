# Remove Import Confirmation & Review Flow — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the entire confirmation and review layer from imports. Once images are processed, they're in — no `awaiting_input` state, no `pending_groups`/`all_confirmed` tracking, no `needs_review` gating, no "Done"/"Confirm Import" button. Simplify the state machine to: `uploading → staging → active → completed/failed/cancelled`.

**Architecture:** Three layers of removal:
1. **Confirmation tracking** — `pending_groups`, `all_confirmed`, `remaining_groups`, `awaiting_input`, `/finalize`, `/confirm` (single-group, dead code)
2. **Review gating** — `needs_review` column on images, `/groups/confirm-review` endpoint, search filtering on `needs_review`, ActivityDock indefinite-retention logic
3. **UI simplification** — remove "Done"/"Confirm Import" button from EditGroupDialog import mode, remove `importJobInitiallyDone` prop, simplify ActivityDock status handling

The EditGroupDialog remains fully functional for viewing/editing import groups — only the confirmation button is removed.

**Tech Stack:** Python/SQLAlchemy (backend), React/TypeScript (frontend), Alembic (migration), pytest (tests)

---

## Simplified State Machine

```
uploading → staging → active → completed / failed
                 ↘ cancelled        ↗
```

`transition_job_status()` becomes:
1. If terminal → no-op
2. If no group jobs → stay current
3. If any group `status == "running"` → `active`
4. If all groups terminal: any failed → `failed`, else → `completed`
5. Set `completed_at` on terminal transitions

---

## Reviewer-Identified Issues (addressed in this revision)

- **Data migration for existing `awaiting_input` rows** — Task 1 includes a backfill step
- **`/confirm` single-group endpoint is dead code** — removed entirely (Task 3)
- **`has_running` semantic change** — preserved as `status == "running"` (not `not in TERMINAL`), matching current behavior (Task 2)
- **Missing files from v1 plan** — added: `test_maintenance.py`, `ActivityDock.test.tsx`, `useImportPersistence.ts`, `importStorage.ts`, design docs (`web-import.md`, `backend.md`, `storage.md`)
- **`needs_review` removal** — fully scoped as new Tasks 4 and 8
- **Staging cleanup without `/finalize`** — the `confirm-all` path already runs all groups via `process_import_job`, which calls `_finalize_import_job` on completion. Staging cleanup happens there for terminal jobs. The 48-hour `expire_stale_jobs` remains as a safety net.

---

### Task 1: Database Migration — Drop columns, backfill `awaiting_input` rows, drop `needs_review`

**Files:**
- Create: `backend/alembic/versions/012_remove_confirmation_and_review.py`
- Modify: `backend/app/models/database.py`

**Step 1: Write migration**

The migration must:
1. Backfill any existing `awaiting_input` jobs to `completed` or `failed` (based on whether any child group failed)
2. Drop `pending_groups` and `all_confirmed` from `import_jobs`
3. Drop `needs_review` column and its index from `images`

```python
"""Remove import confirmation columns and needs_review.

Revision ID: 012
Revises: 011
"""

from alembic import op
import sqlalchemy as sa

revision = "012_remove_confirmation_and_review"
down_revision = "011_import_state_machine"


def upgrade():
    conn = op.get_bind()

    # Backfill awaiting_input jobs based on child group states
    awaiting_jobs = conn.execute(
        sa.text("SELECT id FROM import_jobs WHERE status = 'awaiting_input'")
    ).fetchall()

    for (job_id,) in awaiting_jobs:
        has_failure = conn.execute(
            sa.text(
                "SELECT 1 FROM import_group_jobs "
                "WHERE import_job_id = :jid AND status = 'failed' LIMIT 1"
            ),
            {"jid": job_id},
        ).fetchone()
        new_status = "failed" if has_failure else "completed"
        conn.execute(
            sa.text(
                "UPDATE import_jobs SET status = :s, completed_at = CURRENT_TIMESTAMP "
                "WHERE id = :jid"
            ),
            {"s": new_status, "jid": job_id},
        )

    # Clear needs_review on all images (they're all "in" now)
    conn.execute(sa.text("UPDATE images SET needs_review = 0 WHERE needs_review = 1"))

    op.drop_column("import_jobs", "pending_groups")
    op.drop_column("import_jobs", "all_confirmed")
    op.drop_index("ix_images_needs_review", table_name="images")
    op.drop_column("images", "needs_review")


def downgrade():
    op.add_column(
        "import_jobs",
        sa.Column("all_confirmed", sa.Boolean(), server_default="0", nullable=False),
    )
    op.add_column(
        "import_jobs",
        sa.Column("pending_groups", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "images",
        sa.Column("needs_review", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_images_needs_review", "images", ["needs_review"])
```

**Step 2: Update SQLAlchemy models**

In `backend/app/models/database.py`:
- Remove `pending_groups` column (~line 176)
- Remove `all_confirmed` column (~line 185)
- Remove `awaiting_input` from the status comment (~line 173)
- Remove `needs_review` column from `Image` model (~line 65)

**Step 3: Update Pydantic schemas**

In `backend/app/models/schemas.py`:
- Remove `needs_review: bool = False` from `ImageBase` (~line 73)
- Remove `ConfirmReviewRequest` class (~lines 513-516)
- Remove `remaining_groups` from `ImportConfirmRequest` (~line 425-431)
- Remove `pending_group_count` from `ImportJobResponse` (~line 464)
- Remove `pending_groups` from `ImportJobSummary` (~line 475-491)
- Remove `awaiting_input` from status comments (~line 461)

**Step 4: Commit**

```bash
git add backend/alembic/versions/012_remove_confirmation_and_review.py backend/app/models/database.py backend/app/models/schemas.py
git commit -m "refactor: drop pending_groups, all_confirmed, needs_review columns"
```

---

### Task 2: Simplify `transition_job_status()`

**Files:**
- Modify: `backend/app/services/import_state.py`
- Modify: `backend/tests/unit/test_import_state.py`

**Step 1: Update tests — remove awaiting_input tests, simplify remaining**

- Delete the entire `TestAwaitingInput` class (~lines 207-257)
- Remove `all_confirmed` and `pending_groups` kwargs from all `ImportJob` fixtures across all test classes
- Rename `TestAllTerminalNoPending` to `TestAllTerminal` (the "NoPending" qualifier is meaningless now)

**Step 2: Simplify `transition_job_status`**

Remove lines 53-54 (the `awaiting_input` branch). Remove all references to `job.pending_groups` and `job.all_confirmed`. Remove `awaiting_input` from the state machine comment.

**Important:** Keep `has_running = any(g.status == "running" for g in groups)` — do NOT change to `not in GROUP_TERMINAL_STATUSES`. The current code specifically checks for `"running"` and that's the correct semantic (a queued-but-not-started group shouldn't flip the job to `active`).

**Step 3: Run tests**

```bash
uv run pytest backend/tests/unit/test_import_state.py -v
```

**Step 4: Commit**

```bash
git add backend/app/services/import_state.py backend/tests/unit/test_import_state.py
git commit -m "refactor: simplify transition_job_status — remove awaiting_input path"
```

---

### Task 3: Simplify Backend API Endpoints

**Files:**
- Modify: `backend/app/api/imports.py`

**Step 1: Remove `/confirm` single-group endpoint**

Delete the entire `/confirm` endpoint (~lines 614-711). This is dead code — the frontend always uses `/confirm-all` via auto-confirm. Removing it eliminates the latent bug where a single-confirm job would prematurely complete (no `pending_groups` to hold it in `awaiting_input`).

**Step 2: Remove `/finalize` endpoint**

Delete the entire `/finalize` endpoint (~lines 1020-1093). No longer needed — jobs auto-transition to terminal via `transition_job_status()`.

**Step 3: Simplify `/confirm-all` endpoint**

Remove `job.all_confirmed = True` and `job.pending_groups = 0` lines (~808-812). Just set `job.status = "active"`.

**Step 4: Remove `pending_groups = 0` from `/cancel`, `/fail`**

In `/cancel` (~lines 1153, 1167) and `/fail` (~line 1228), remove `job.pending_groups = 0` lines.

**Step 5: Remove `pending_groups` from `/analyse` (upload)**

In the analysis handler (~line 392), remove `job.pending_groups = len(import_groups)`.

**Step 6: Remove `pending_groups` from `/status` and `/active` responses**

In `/status` (~lines 865-866), remove `detected_group_count` and `pending_group_count` calculations. Replace `total_groups` with `len(group_jobs)`.

In `/active` (~lines 935-963), remove the `jobs_with_unreviewed` batch query and the indefinite-retention logic for completed jobs with unreviewed images. All completed jobs should follow the standard 1-hour TTL.

In `/active` (~lines 970-974), remove `pending_groups` from summary construction. Set `total_groups = len(groups)`.

**Step 7: Commit**

```bash
git add backend/app/api/imports.py
git commit -m "refactor: remove /confirm, /finalize, pending_groups tracking, needs_review retention"
```

---

### Task 4: Remove `needs_review` from Pipeline and Search

**Files:**
- Modify: `backend/pipeline/ingestion.py`
- Modify: `backend/app/api/search.py`
- Modify: `backend/app/api/groups.py`

**Step 1: Remove `needs_review` from pipeline**

In `ingestion.py`:
- Remove `needs_review` parameter from `_run_group` signature (~line 1071) and all internal propagation (~line 1169)
- Remove `needs_review=True` from `process_group` call (~line 1479) and `process_import_job` call (~line 1541)
- Remove `needs_review` from `prepare_image` (~lines 242, 267) and from `image_data` dicts (~lines 328, 469)
- Remove `needs_review` from `_create_image_from_data` (~line 115)

**Step 2: Remove search filtering on `needs_review`**

In `search.py`:
- Remove `reviewed = Image.needs_review.is_(False)` filter from facets endpoint (~line 30) and its application (~lines 35, 45, 57)
- Remove `exclude_needs_review` query parameter (~line 143) and its filter (~lines 181-182) from main search endpoint

**Step 3: Remove `/groups/confirm-review` endpoint**

In `groups.py`:
- Delete the `confirm_review` endpoint (~lines 408-434)
- Remove the `ConfirmReviewRequest` import (~line 18)

**Step 4: Run backend tests**

```bash
uv run pytest backend/tests/ -v --timeout=60
```

**Step 5: Commit**

```bash
git add backend/pipeline/ingestion.py backend/app/api/search.py backend/app/api/groups.py
git commit -m "refactor: remove needs_review from pipeline, search, and groups API"
```

---

### Task 5: Simplify Pipeline `_finalize_import_job`

**Files:**
- Modify: `backend/pipeline/ingestion.py`
- Modify: `backend/pipeline/maintenance.py`

**Step 1: Simplify `_finalize_import_job`**

Remove the single-confirm vs confirm-all branching (~lines 1351-1430). The simplified flow:
1. If cancelled → sweep late-arriving images, return
2. Call `transition_job_status(db, job_id)`
3. If terminal and failed → clean up failed-group images (existing logic)
4. If terminal → clean up staging directory
5. Log result

The `if not job.all_confirmed:` branch (~line 1351) and its sub-branches for `awaiting_input` (~line 1363) are removed entirely. All paths now go through `transition_job_status()`.

**Step 2: Update maintenance.py**

- Remove `"awaiting_input"` from `stale_statuses` set (~line 211)

**Step 3: Commit**

```bash
git add backend/pipeline/ingestion.py backend/pipeline/maintenance.py
git commit -m "refactor: simplify _finalize_import_job — single path through transition_job_status"
```

---

### Task 6: Update All Backend Tests

**Files:**
- Modify: `backend/tests/unit/test_maintenance.py`
- Modify: `backend/tests/integration/test_imports_status.py`
- Modify: `backend/tests/integration/test_confirm_endpoint.py`
- Modify: `backend/tests/integration/test_process_import_group.py`
- Modify: `backend/tests/unit/test_batch_isolation.py`
- Modify: `backend/tests/unit/test_process_batch_cleanup.py`

**Step 1: Update maintenance tests**

In `test_maintenance.py`:
- Remove `awaiting_input` job fixtures (~lines 276-279)
- Remove `awaiting_input` from "no interrupted jobs" assertions (~line 302)

**Step 2: Update import status tests**

In `test_imports_status.py`:
- Remove `test_awaiting_input_with_pending_groups` (~line 255-274)
- Remove entire `TestFinalizeImport` class (~lines 451-580)
- Remove `TestActiveImportsPendingGroups` class (~lines 583-619)
- Remove `test_pending_groups_reflected_in_status` (~line 770-783)
- Remove `TestActiveImportsUnreviewed` class (~lines 917-960) — no more `needs_review` retention
- Update `test_mixed_terminal_status_with_all_confirmed` — remove `all_confirmed` setup, keep as test that mixed terminal → `failed`
- Remove `awaiting_input` from `test_fail_disallowed_statuses` parametrize (~line 871-884)

**Step 3: Update confirm endpoint tests**

In `test_confirm_endpoint.py`:
- Remove `remaining_groups` from any request bodies
- If tests call `/confirm` (single-group), rewrite to use `/confirm-all`

**Step 4: Update process import group tests**

In `test_process_import_group.py`:
- Remove `all_confirmed=True` from test fixtures — this field no longer exists
- Remove `TestAllConfirmedAutoComplete` class (~lines 874-954)
- Update `test_import_job_stays_active_after_single_confirm` (~line 275) — with no pending tracking, the job should auto-complete via `transition_job_status`
- Remove `test_completed_at_not_set_on_single_confirm` (~line 797-823)

**Step 5: Update unit test fixtures**

In `test_batch_isolation.py` (~line 22) and `test_process_batch_cleanup.py` (~line 40): remove `needs_review` from `image_data` fixture dicts.

**Step 6: Run all backend tests**

```bash
uv run pytest backend/tests/ -v --timeout=60
```

**Step 7: Commit**

```bash
git add backend/tests/
git commit -m "test: update all backend tests for simplified import flow"
```

---

### Task 7: Frontend — Remove Confirmation & Review Tracking

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api/importApi.ts`
- Modify: `frontend/src/lib/api/groupApi.ts`
- Modify: `frontend/src/lib/importStorage.ts`
- Modify: `frontend/src/hooks/useImportState.ts`
- Modify: `frontend/src/hooks/useImportPolling.ts`
- Modify: `frontend/src/hooks/useActiveImports.ts`
- Modify: `frontend/src/hooks/useImportReviewPolling.ts`
- Modify: `frontend/src/hooks/useImportPersistence.ts`

**Step 1: Update types**

In `types/index.ts`:
- Remove `needs_review: boolean` from `Image` interface (~line 23)
- Remove `remaining_groups` from `ImportConfirmRequest` (~line 236-241)
- Remove `pending_groups` from `ImportJobSummary` (~line 387-401)
- Remove `'awaiting_input'` from any status type unions

**Step 2: Remove API methods**

In `importApi.ts`:
- Remove `confirm` (single-group) method (~lines 69-72) — endpoint no longer exists
- Remove `finalize` method (~lines 94-103)

In `groupApi.ts`:
- Remove `confirmReview` method (~lines 62-67) — endpoint no longer exists

**Step 3: Simplify `useImportState`**

- Remove `handleConfirmGroup` entirely — single-confirm path is gone
- Remove `remaining_groups` construction
- Remove `handleFinalize`
- Remove all three from the hook's return value

**Step 4: Update `useImportPolling`**

- Remove `'awaiting_input'` → `'preview'` mapping from `backendStatusToDialogState`

**Step 5: Simplify `useActiveImports`**

- Remove `'awaiting_input'` from status type union (~line 32)
- Remove `pendingGroups > 0` from `hasActive` logic (~lines 183-191)
- Remove `pendingGroups` mapping (~line 224)
- Remove pending_groups localStorage supplement logic (~lines 250-258)

**Step 6: Evaluate `useImportReviewPolling`**

This hook polls for running groups during the EditGroupDialog's live import view. The `pendingGroups` here tracks *running* groups (not DB `pending_groups`), and `allDone` means all groups finished processing. This is still useful for the EditGroupDialog — keep the hook but rename `pendingGroups` to `runningGroups` for clarity if feasible.

**Step 7: Clean up `useImportPersistence` and `importStorage`**

- In `useImportPersistence.ts`: remove `awaiting_input` comment/references
- In `importStorage.ts`: remove `pendingGroups` from `ImportJobIndexEntry` (~line 35) and from `saveImportState` (~line 219)

**Step 8: Commit**

```bash
git add frontend/src/
git commit -m "refactor: remove confirmation and review tracking from frontend"
```

---

### Task 8: Frontend — Simplify EditGroupDialog, ActivityDock, Gallery

**Files:**
- Modify: `frontend/src/components/EditGroupDialog.tsx`
- Modify: `frontend/src/components/EditGroupDialog.test.tsx`
- Modify: `frontend/src/components/ActivityDock.tsx`
- Modify: `frontend/src/components/ActivityDock.test.tsx`
- Modify: `frontend/src/pages/Gallery.tsx`

**Step 1: Simplify EditGroupDialog**

- Remove `importJobInitiallyDone` prop (~lines 57-61)
- Remove `handleDone` logic that calls `groupApi.confirmReview()` (~lines 220-239). Replace with a simple close handler: `onSave()` then `onClose()`. No review confirmation needed.
- Remove the bottom "Done"/"Confirm Import" button (~lines 867-897). The dialog closes via the X button or Escape — the user is just viewing/editing the group.
- Remove `hasPendingGroups` state that disabled the button (~line 351)
- The X button (~line 382) should call a simple close: `onSave(); onClose()`

**Step 2: Update EditGroupDialog tests**

In `EditGroupDialog.test.tsx`:
- Remove the `confirmReview` mock (~line 21)
- Remove/update test `"does NOT call confirmReview when dialog is dismissed via Escape"` (~lines 42-62) — `confirmReview` no longer exists. Replace with a simpler test that Escape calls `onClose`.

**Step 3: Update ActivityDock**

- Remove `awaiting_input` from `canCancel` check (~line 279)
- Remove `awaiting_input` case from `ImportStatusIcon` switch (~lines 503-504)
- Remove `awaiting_input` case from `ImportStatusText` switch (~lines 552-556)
- Remove `pendingGroups` usage in status text

**Step 4: Update ActivityDock tests**

In `ActivityDock.test.tsx`:
- Remove `pendingGroups: 3` from test fixtures (~line 33)

**Step 5: Update Gallery.tsx**

- Remove `'awaiting_input'` from `importJobInitiallyDone` check (~lines 192-194)
- Remove `'awaiting_input'` case from `onOpenJob` handler (~lines 270-278)

**Step 6: Commit**

```bash
git add frontend/src/
git commit -m "refactor: remove Done button and review flow from EditGroupDialog"
```

---

### Task 9: Update Design Documentation

**Files:**
- Modify: `design/import-state-machine.md`
- Modify: `design/web-import.md`
- Modify: `design/backend.md`
- Modify: `design/storage.md`

**Step 1: Update `import-state-machine.md`**

- Remove `awaiting_input` from state diagram and status table
- Remove `pending_groups` and `all_confirmed` from key design decisions section
- Remove `/finalize` references
- Simplify transition function description (4 rules instead of 6)
- Update frontend status mapping (remove `awaiting_input` case)
- Update activity tray behavior table (remove `awaiting_input` row)
- Remove section on `needs_review` retention in ActivityDock (~line 120)
- Update related files table (remove `/confirm`, `/finalize` references)

**Step 2: Update `web-import.md`**

- Remove `awaiting_input` from any endpoint availability guards (~line 197)
- Remove `/confirm` (single-group) endpoint documentation
- Remove `/finalize` endpoint documentation
- Remove `remaining_groups` from `/confirm-all` docs
- Remove `needs_review` references

**Step 3: Update `backend.md`**

- Remove `awaiting_input` from ImportStateService description (~line 176)

**Step 4: Update `storage.md`**

- Remove `needs_review` from database schema documentation (~line 40)

**Step 5: Commit**

```bash
git add design/
git commit -m "docs: update all design docs for simplified import flow"
```

---

### Task 10: Final Verification

**Step 1: Run ruff format/check**

```bash
uv run ruff format backend/ && uv run ruff check backend/ --fix
```

**Step 2: Run ESLint/Prettier**

```bash
cd frontend && npx prettier --write src/ && npx eslint src/ --fix
```

**Step 3: Run all backend tests**

```bash
uv run pytest backend/tests/ -v --timeout=60
```

**Step 4: Run frontend tests**

```bash
cd frontend && npm test
```

**Step 5: Final commit if any formatting changes**

```bash
git add -A && git commit -m "style: format after import confirmation and review removal"
```
