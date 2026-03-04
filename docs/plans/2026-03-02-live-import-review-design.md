# Live Import Review — Design Doc

**Date:** 2026-03-02
**Status:** Approved

## Context

After a file import is confirmed and background processing begins, users currently see a non-editable progress dialog (`ImportDialog` in `processing` state showing `GroupStatusRow` components). Once all groups finish, they receive a "Review" toast to open `EditGroupDialog`. There is no way to start reviewing completed groups while others are still processing.

**Goal:** Allow users to open `EditGroupDialog` at any point during an active import (via the ActivityDock or the existing "Review" toast), see pending groups as non-interactive stubs with progress spinners, and immediately begin editing any group that has finished processing. Existing `ImportDialog` behaviour is unchanged.

---

## Architecture

### High-level flow

```
Upload → ImportDialog (processing state, unchanged)
       ↓
ActivityDock: job card visible (active or completed)
       ↓  [user clicks active or completed job]
EditGroupDialog (importJobId mode):
  - sidebar: completed groups (interactive) + pending stubs (spinner)
  - polls /imports/{jobId}/status every 3 s
  - as each group completes → loads it into the dialog
  - "Confirm Import" disabled while pending stubs > 0
```

### Key data source

`GET /imports/{jobId}/status` → `ImportJobResponse.groups: ImportGroupStatus[]`

```ts
interface ImportGroupStatus {
  group_job_id: string
  group_name: string
  total_files: number
  processed_files: number
  failed_files: number
  status: string          // 'running' | 'completed' | 'failed' | 'cancelled'
  group_id?: number | null  // set when status === 'completed'
}
```

No backend changes required.

---

## New / Modified Files

### 1. `frontend/src/hooks/useImportReviewPolling.ts` *(new)*

Polls `/imports/{jobId}/status` while any groups are still `running`.

```ts
interface UseImportReviewPollingOptions {
  importJobId: string | null | undefined
  onGroupCompleted: (groupId: number) => void  // fires per new completion
  enabled: boolean
}

interface UseImportReviewPollingReturn {
  pendingGroups: ImportGroupStatus[]  // status = 'running'
  failedGroups: ImportGroupStatus[]   // status = 'failed' | 'cancelled'
  allDone: boolean                    // no more running groups
  pollError: boolean
}
```

- Immediate fetch on mount (no initial delay)
- 3-second interval while `!allDone && enabled`
- Tracks seen group IDs in a ref; only calls `onGroupCompleted` for *new* completions
- Sets `allDone = true` when no group has `status === 'running'`
- Stops interval on `!enabled` or `allDone`

### 2. `frontend/src/hooks/useEditGroupLoad.ts` *(modified)*

Current import-review mode re-fetches *all* group IDs when `groupIds` changes, replacing `groups` state.
Change: use a `loadedGroupIdsRef` (`Set<number>`) to track already-fetched IDs.

When `groupIds` grows:
- Compute `newIds = groupIds.filter(id => !loadedGroupIdsRef.has(id))`
- Fetch only `newIds`; append resulting `EditableGroupState[]` to existing `groups` via `setGroups(prev => [...prev, ...newGroups])`
- Only call `setActiveTab` on the *first* load (not incremental appends)
- Reset `loadedGroupIdsRef` inside `resetLoad()`

### 3. `frontend/src/components/EditGroupDialog.tsx` *(modified)*

**New prop:**
```ts
importJobId?: string
```

**New internal state:**
```ts
const [liveGroupIds, setLiveGroupIds] = useState<number[]>(groupIds ?? [])
```

**Polling integration:**
```ts
const { pendingGroups, failedGroups, allDone } = useImportReviewPolling({
  importJobId,
  onGroupCompleted: (id) => setLiveGroupIds(prev => [...prev, id]),
  enabled: open && !!importJobId,
})
```

Pass `liveGroupIds` (instead of `groupIds`) to `useEditGroupLoad`.

**`isImportReview` flag** (used for "Confirm Import" label and `confirmReview` logic):
```ts
const isImportReview = !!importJobId || liveGroupIds.length > 0
```

**Sidebar additions** (after existing group rows, only when `importJobId` provided):
```tsx
{pendingGroups.map(stub => (
  <div key={stub.group_job_id} className="flex items-center gap-2 pl-3 pr-3 py-2 opacity-60 cursor-not-allowed select-none">
    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />
    <span className="flex-1 text-[12px] text-muted-foreground truncate">{stub.group_name}</span>
    <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
      {stub.processed_files}/{stub.total_files}
    </span>
  </div>
))}
{failedGroups.map(stub => (
  <div key={stub.group_job_id} className="flex items-center gap-2 pl-3 pr-3 py-2 opacity-60 select-none">
    <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
    <span className="flex-1 text-[12px] text-muted-foreground truncate">{stub.group_name}</span>
    <span className="text-[11px] text-destructive/60 shrink-0">{stub.failed_files} failed</span>
  </div>
))}
```

Sidebar header count: `groups.length + pendingGroups.length + failedGroups.length`

**Footer "Confirm Import" button gating:**
```ts
const hasPendingGroups = importJobId ? !allDone : false
const confirmDisabled = isBusy || hasPendingGroups
```

Button label while pending: `"Waiting for ${pendingGroups.length} group(s)…"`

**`handleDone` / `confirmReview`:** uses `liveGroupIds` (the accumulated list) instead of the `groupIds` prop.

### 4. `frontend/src/hooks/useGalleryDialogs.ts` *(modified)*

Replace:
```ts
importReviewGroupIds: number[] | null
setImportReviewGroupIds: (ids: number[] | null) => void
```

With:
```ts
importLiveJobId: string | null
setImportLiveJobId: (id: string | null) => void
```

Remove the `importReviewGroupIds` state variable and all references.

### 5. `frontend/src/pages/Gallery.tsx` *(modified)*

**Toast "Review" handler** (currently fetches group IDs upfront):
```ts
// BEFORE:
const status = await importApi.status(jobId)
const ids = status.groups.filter(g => g.group_id).map(g => g.group_id!)
dialogs.setImportReviewGroupIds(ids)

// AFTER:
dialogs.setImportLiveJobId(jobId)
```

**ActivityDock `onOpenJob` handler:**
```ts
// BEFORE:
if (status === 'completed' && pendingGroups === 0) {
  // fetch groupIds → setImportReviewGroupIds
} else if (status === 'failed' || status === 'broken') {
  dialogs.setImportSummaryJobId(jobId)
} else {
  dialogs.openImportDialog(jobId)  // reconnect
}

// AFTER:
if (status === 'failed' || status === 'broken') {
  dialogs.setImportSummaryJobId(jobId)
} else if (status === 'completed' || status === 'active') {
  dialogs.setImportLiveJobId(jobId)           // covers both in-progress and done
} else {
  dialogs.openImportDialog(jobId)             // uploading/staging → ImportDialog
}
```

**EditGroupDialog (import-review instance):**
```tsx
// BEFORE:
<EditGroupDialog
  groupIds={importReviewGroupIds ?? undefined}
  open={importReviewGroupIds !== null}
  onSave={() => { ... dialogs.setImportReviewGroupIds(null) ... }}
  onClose={() => dialogs.setImportReviewGroupIds(null)}
/>

// AFTER:
<EditGroupDialog
  importJobId={importLiveJobId ?? undefined}
  open={importLiveJobId !== null}
  onSave={() => { ... dialogs.setImportLiveJobId(null) ... }}
  onClose={() => dialogs.setImportLiveJobId(null)}
/>
```

The `importReviewJobIdRef` (used to dismiss the ActivityDock job on save) is renamed to `importLiveJobIdRef` and set to `importLiveJobId` whenever it changes.

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| User closes EditGroupDialog while groups still processing | Dialog closes; job continues in ActivityDock; user can re-open |
| All groups fail | `failedGroups` stubs shown; `allDone=true`; "Confirm Import" enabled (reviews successfully-processed groups, if any) |
| Job already completed when dialog opens | First poll returns all groups as 'completed'; no stubs shown; dialog behaves like current import-review mode |
| Connection lost during polling | `pollError=true`; stubs stay; user can retry by closing and reopening |
| Single-group import (only 1 group) | No sidebar shown (same as today); main area shows spinner until group loads |

---

## Verification

1. Start a multi-file import (≥3 groups worth of images)
2. While processing, click the ActivityDock job card → `EditGroupDialog` opens
3. Confirm: pending groups show as spinners in sidebar, are not clickable
4. Confirm: as each group finishes, it appears in the sidebar as interactive and can be edited
5. Confirm: "Confirm Import" is disabled until all spinners resolve
6. Confirm: after clicking "Confirm Import", gallery refreshes and job dismisses from ActivityDock
7. Repeat for a completed job (opened via "Review" toast): all groups load immediately, no spinners

**Existing tests to run:**
```
uv run pytest backend/tests/
```

**Frontend lint:**
```
cd frontend && npx tsc --noEmit && npx eslint src/
```
