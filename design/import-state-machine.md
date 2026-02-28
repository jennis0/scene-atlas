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

Terminal statuses: `completed`, `failed`, `cancelled`, `expired`. Once terminal, status never changes.

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

- `staging` = user hasn't confirmed any groups yet (initial review)
- `awaiting_input` = user has confirmed some groups, they've finished, but unconfirmed groups remain

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
    case 'awaiting_input': return 'preview'
    case 'active': return 'processing'
    default: return 'done'  // completed, failed, cancelled, expired
  }
}
```

## Activity Tray Behavior

| Status | Icon | Counts as "active" (spinner on FAB) |
|--------|------|-------------------------------------|
| `uploading` | Upload (pulsing) | Yes |
| `staging` | Clock | No |
| `awaiting_input` | Bell (amber) | No |
| `active` / `running` | Loader (spinning) | Yes |
| `completed` | Check | No |
| `failed` | Alert circle | No |
| `cancelled` | Ban | No |

## Related Files

| File | Purpose |
|------|---------|
| `backend/app/services/import_state.py` | `transition_job_status()` — single authoritative transition function |
| `backend/app/models/database.py` | `ImportJob` model with `status`, `pending_groups`, `all_confirmed` |
| `backend/app/api/imports.py` | All import endpoints |
| `backend/pipeline/ingestion.py` | `_finalize_import_job()` — calls `transition_job_status()` after group processing |
| `backend/pipeline/maintenance.py` | `expire_stale_jobs()` — includes `awaiting_input` in stale set |
| `frontend/src/hooks/useImportPolling.ts` | `backendStatusToDialogState()` helper, polling with group_job_id matching |
| `frontend/src/hooks/useImportPersistence.ts` | Reconnection using backend-authoritative status |
| `frontend/src/hooks/useImportState.ts` | `remaining_groups` in confirm requests, `group_job_id` storage |
| `frontend/src/hooks/useActiveImports.ts` | `awaiting_input` in status type |
| `frontend/src/components/ActivityDock.tsx` | Status icons/text for `awaiting_input` |

## Migration

Migration `011_import_state_machine.py` adds `pending_groups` column with default 0. Backfills non-terminal jobs from `analysis_result` JSON data (subtracting already-submitted groups).
