# Import Job State Machine

## Overview

Import jobs track the lifecycle of a multi-group image import from upload through processing to completion. The import flow uses an **explicit state machine** where `ImportJob.status` is the single source of truth — status is never derived from child group states.

## State Machine

```
uploading → staging → active ↔ awaiting_input → completed/failed
                 ↘ cancelled        ↗              ↗
```

| Status | Meaning | Set by |
|--------|---------|--------|
| `uploading` | Files being uploaded to staging | `POST /init` |
| `staging` | Analysis complete, user reviewing before first confirm | `POST /upload` |
| `active` | At least one group currently processing | `transition_job_status()` |
| `awaiting_input` | All submitted groups terminal, unconfirmed groups remain | `transition_job_status()` |
| `completed` | All groups done successfully, no unconfirmed groups | `transition_job_status()` or `/finalize` |
| `failed` | All groups done, at least one failure, no unconfirmed groups | `transition_job_status()` or `/finalize` |
| `cancelled` | User cancelled the import | `POST /cancel` |
| `expired` | Stale job cleaned up by maintenance | `expire_stale_jobs()` |

Terminal statuses: `completed`, `failed`, `cancelled`, `expired`, `broken`. Once terminal, status never changes.

### `broken` status (added: import pipeline robustness)

`broken` is a pseudo-terminal status applied at server startup by `mark_interrupted_jobs()` in `maintenance.py`. Any job in `uploading`, `staging`, or `active` at the time the server starts was interrupted mid-flight and cannot be resumed. These are transitioned to `broken` so the ActivityDock can show them as unrecoverable and the user can dismiss them.

- `broken` is NOT a normal state machine transition — it is set directly by `mark_interrupted_jobs()`, bypassing `transition_job_status()`.
- The frontend maps `broken` to the `done` dialog state and shows an `AlertCircle` icon (same as `failed`).
- `ImportSummaryDialog` is shown for `broken` and `failed` jobs so users can inspect what went wrong before dismissing.

### `/fail` endpoint

`POST /imports/{job_id}/fail` accepts `{ error_message: string }` and transitions the job from `uploading` or `staging` → `failed`, recording the error message on `ImportJob.error_message`. Guards against transitioning from `active` or already-terminal states.

Used by the frontend in place of `/cancel` when an upload or analysis error occurs — semantically more accurate since the user did not request cancellation; the job failed.

- If `/fail` is unavailable (e.g. network error during the call itself), the frontend falls back to `/cancel` to ensure staging cleanup still occurs.
- `error_message` is surfaced via `ImportJobSummary.error_message` and shown in `ImportSummaryDialog`.

## Key Design Decisions

### 1. Backend-authoritative status

Prior to this design, import job status was derived from child group states in 5 different locations (3 backend, 2 frontend), each with slightly different logic. This caused bugs when derivations disagreed.

Now:
- `ImportJob.status` in the database is the sole source of truth
- All status changes go through `transition_job_status()` (in `backend/app/services/import_state.py`)
- The frontend reads status from the backend and maps it to dialog state — it never derives status locally
- Endpoints like `GET /status` and `GET /active` read the DB column directly

### 2. Explicit pending_groups counter

The `ImportJob.pending_groups` column tracks how many groups the user hasn't yet confirmed. This replaces the fragile approach of comparing `analysis_result` group count against submitted `ImportGroupJob` rows, which broke when users merged, split, or restructured groups in the preview UI.

- Set to `len(groups)` when `POST /upload` completes analysis
- Synced on each `POST /confirm`: the frontend includes `remaining_groups: string[]` (names of still-unconfirmed groups), and the backend sets `pending_groups = len(remaining_groups)`
- Set to 0 on `POST /confirm-all` and `POST /finalize`

### 3. group_job_id for robust matching

`ImportGroupStatus` responses include `group_job_id` — the stable backend ID for each group job. The frontend uses this for matching status updates instead of matching by `group_name`, which was brittle when groups were renamed.

### 4. awaiting_input vs staging

- `staging` = analysis complete, auto-confirm pending (transient — auto-confirm fires immediately)
- `awaiting_input` = not used in normal flow since auto-confirm-all; retained for backend compatibility

The activity tray shows different icons: clock for staging, bell for awaiting_input, spinner for active.

## Transition Function

`transition_job_status(db, job_id)` in `backend/app/services/import_state.py`:

1. If job is already terminal → no-op (return current status)
2. If no group jobs exist → stay in current status (staging/uploading)
3. If any group is `running` → `active`
4. If all groups are terminal:
   - If `pending_groups > 0` and not `all_confirmed` → `awaiting_input`
   - If any group failed → `failed`
   - Otherwise → `completed`
5. Sets `completed_at` for terminal transitions
6. Always sets `updated_at`

Called after: group finishes processing, user confirms a group, user finalizes, user cancels.

## Frontend Status Mapping

```typescript
function backendStatusToDialogState(status: string): DialogState {
  switch (status) {
    case 'uploading': return 'upload'
    case 'staging':
    case 'awaiting_input': return 'preview'  // transient: auto-confirm fires immediately
    case 'active': return 'processing'
    default: return 'done'  // completed, failed, cancelled, expired
  }
}
```

Note: `'preview'` is a transient internal dialog state — the auto-confirm useEffect in `useImportState` fires immediately when the state becomes `'preview'`, so users never see it.

## Activity Tray Behavior

| Status | Icon | Counts as "active" (spinner on FAB) |
|--------|------|-------------------------------------|
| `uploading` | Upload (pulsing) | Yes |
| `staging` | Clock | No |
| `awaiting_input` | Bell (amber) | No |
| `active` / `running` | Loader (spinning) | Yes |
| `completed` | Check | No |
| `failed` | Alert circle | No |
| `broken` | Alert circle | No |
| `cancelled` | Ban | No |

Completed jobs with `needs_review=True` images remain in the ActivityDock's `/active` list indefinitely — they are not subject to the 1-hour recency TTL. This ensures users can always find unreviewed imports via the ActivityDock. Once all images are reviewed (i.e. `needs_review` cleared), the TTL applies and the job is eventually pruned from the list.

## Related Files

| File | Purpose |
|------|---------|
| `backend/app/services/import_state.py` | `transition_job_status()` — single authoritative transition function |
| `backend/app/models/database.py` | `ImportJob` model with `status`, `pending_groups`, `all_confirmed`, `error_message` |
| `backend/app/api/imports.py` | All import endpoints including `POST /{job_id}/fail` |
| `backend/pipeline/ingestion.py` | `_finalize_import_job()` — calls `transition_job_status()` after group processing |
| `backend/pipeline/maintenance.py` | `expire_stale_jobs()` — includes `awaiting_input` in stale set; `mark_interrupted_jobs()` — marks `uploading`/`staging`/`active` as `broken` at startup |
| `frontend/src/hooks/useImportPolling.ts` | `backendStatusToDialogState()` helper, polling with group_job_id matching |
| `frontend/src/hooks/useImportPersistence.ts` | Reconnection using backend-authoritative status |
| `frontend/src/hooks/useImportState.ts` | `remaining_groups` in confirm requests, `group_job_id` storage, auto-confirm retry logic |
| `frontend/src/hooks/useActiveImports.ts` | `awaiting_input`/`broken` in status type; connection-lost tracking |
| `frontend/src/components/ActivityDock.tsx` | Status icons/text including `broken`; WifiOff connection-lost indicator |
| `frontend/src/components/ImportSummaryDialog.tsx` | Error summary shown for `failed`/`broken` jobs |

## Migration

Migration `011_import_state_machine.py` adds `pending_groups` column with default 0. Backfills non-terminal jobs from `analysis_result` JSON data (subtracting already-submitted groups).
