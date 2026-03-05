# Ingest Error & Warning Reporting — Stage 3 Handover Document

**Date:** 2026-03-05
**Status:** Ready for implementation
**Branch:** Create a new worktree from main

## What Was Done (Stages 1 & 2)

Stage 2 is complete and merged to main (`6a078c9`). The backend now fully tracks and
exposes per-file errors, warnings, relative paths, upload-phase skips, and total file
sizes. The frontend captures all this data through the polling and upload hooks.

### What the data layer now provides

- **`/api/imports/{job_id}/status`** returns:
  - `groups[].file_errors[]` — per-file `{filename, relative_path, reason, stage, severity}`
  - `job_warnings[]` — upload-phase skips and Qdrant non-fatal failures
  - `total_file_size` — accumulated bytes across all uploaded files
  - `created_at`, `completed_at` — duration can be computed from these

- **`/api/imports/active`** returns per-summary:
  - `failed_files` — total failed files across all groups
  - `warning_count` — number of job-level warnings

- **Frontend state** (`ActiveImportJob`):
  - `failedFiles: number`, `warningCount: number` — available on every job in the dock
  - `EditableGroupState.file_errors` — polled and kept up to date in `useImportPolling`

- **Shared type** `ImportFileError` in `frontend/src/types/index.ts`:
  ```typescript
  export interface ImportFileError {
    filename: string
    relative_path?: string | null
    reason: string
    stage: string
    severity?: 'error' | 'warning'
  }
  ```

---

## Stage 3: What Needs Building

Stage 3 is entirely frontend UI. The data is all there — it just needs to be displayed.

### The Goal

Replace the current "All done, X groups imported" screen with a single
`ImportDetailsDialog` that:
1. Opens automatically at import completion (instead of `ImportDonePane`)
2. Is also accessible later from the activity dock (replacing `ImportSummaryDialog`)
3. Adapts its appearance to job status: clean / with-issues / failed / broken

The activity dock pill should also visually indicate "completed with issues" jobs.

---

## Implementation

### Component 1: `ImportDetailsDialog`

**File to evolve:** `frontend/src/components/ImportSummaryDialog.tsx`
→ Rename/replace with `ImportDetailsDialog.tsx`

`ImportSummaryDialog` (263 lines) already fetches `/status` on open, renders a groups
table, and shows per-file error lists for failed jobs. It needs to be extended to:

**Header area:**
```
Import Complete                     ← green
Import Complete — 3 issues          ← amber (any file_errors or job_warnings)
Import Failed                       ← red (job status = failed/broken)

Dark Forest Maps · imported from upload
47 images imported · 312 MB · took 2m 14s
```

Stats computation:
- Image count: sum `groups[].processed_files - groups[].failed_files`
- File size: `total_file_size` from the response (format with `formatBytes`)
- Duration: `completedAt - createdAt` (both are ISO strings on `ImportJobResponse`)

**Groups table** — already exists, keep it.

**Issues sections** (new — only shown when there's content):
- **Skipped files** — `job_warnings` where `stage === 'upload'`
- **Errors** — all `file_errors` across groups where `severity === 'error'` (or no severity)
- **Warnings** — `job_warnings` where `stage !== 'upload'`, plus `file_errors` where `severity === 'warning'`

Each entry shows: filename, `relative_path` (if different from filename), reason.

**Footer:**
- "Review imported images" → `onReview(groupId)` → opens `EditGroupDialog` for the first group
- "Close"
- "Cancel & Clean Up" — only when `status === 'failed' || status === 'broken'`

**Props interface:**
```typescript
interface ImportDetailsDialogProps {
  jobId: string | null
  open: boolean
  onClose: () => void
  onCancel: (jobId: string) => void   // existing — keep
  onReview?: (groupId: number) => void // new — for "Review imported images"
}
```

**Use the `frontend-design` skill** to design this component before implementing.

---

### Component 2: ActivityDock visual indicator

**File:** `frontend/src/components/ActivityDock.tsx`

The dock already receives `failedFiles: number` and `warningCount: number` on each
`ActiveImportJob`. Currently these are unused in the UI.

Change the completed-job row to show:
- **Clean completion** (failedFiles === 0 && warningCount === 0): green check, "Review import ›"
- **Completed with issues** (failedFiles > 0 || warningCount > 0): amber warning icon,
  "X imported, Y issues ›" (X = completedGroups, Y = failedFiles + warningCount)

Both still call `onOpenJob(jobId)`.

---

### Component 3: `ImportDialog` — auto-open `ImportDetailsDialog` on completion

**File:** `frontend/src/components/ImportDialog.tsx`

Currently at line 229, when state reaches the done phase, it renders `<ImportDonePane>`.

Change this to:
1. Close `ImportDialog` when processing completes
2. Open `ImportDetailsDialog` with the completed `jobId`

The simplest approach: add an `onImportComplete(jobId: string)` callback prop to
`ImportDialog`. The parent (`Gallery.tsx`) handles opening `ImportDetailsDialog`.

---

### Component 4: Gallery routing

**File:** `frontend/src/pages/Gallery.tsx`

Currently at line 247–268, `ImportSummaryDialog` is already rendered. It's triggered by
`onOpenJob` from the activity dock.

Changes needed:
1. Replace `ImportSummaryDialog` with `ImportDetailsDialog`
2. Wire up `onImportComplete` from `ImportDialog` to open `ImportDetailsDialog`
3. In `onOpenJob` handler (line 264): for completed jobs, open `ImportDetailsDialog`;
   for running/failed jobs, the existing logic already opens the right thing
4. In `ImportDetailsDialog.onReview`: navigate to `EditGroupDialog` for the given groupId
   (use existing `handleOpenEditGroup` pattern)

---

### Remove `ImportDonePane`

**File:** `frontend/src/components/import/ImportDonePane.tsx`

Delete this file once `ImportDialog` no longer imports it.

---

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/ImportSummaryDialog.tsx` | Evolve into `ImportDetailsDialog` — new header, issues sections, footer |
| `frontend/src/components/import/ImportDonePane.tsx` | Delete |
| `frontend/src/components/ImportDialog.tsx` | Remove `ImportDonePane`; call `onImportComplete(jobId)` on completion |
| `frontend/src/components/ActivityDock.tsx` | Add amber warning state for completed-with-issues |
| `frontend/src/pages/Gallery.tsx` | Wire `ImportDetailsDialog`; handle `onImportComplete`; update `onOpenJob` |

---

## Key Data Already Available

```typescript
// From /status endpoint (ImportJobResponse):
job.status          // 'completed' | 'failed' | 'broken' | ...
job.created_at      // ISO string
job.completed_at    // ISO string | null
job.total_file_size // bytes (0 if not tracked)
job.source_label    // filename or folder name
job.groups[]        // per-group with file_errors[]
job.job_warnings[]  // upload-phase skips + Qdrant warnings

// From ActiveImportJob (activity dock):
job.failedFiles     // number
job.warningCount    // number
job.status          // current status
job.label           // display name
```

---

## Using the `frontend-design` Skill

Per `CLAUDE.md`, use the `frontend-design` skill for all frontend UI design. Invoke it
with:
```
/frontend-design
```
before designing `ImportDetailsDialog`. Provide the data structures, status variants,
and the sections described above as input to the skill.

---

## Manual Verification Checklist

1. **Clean import:** Upload valid images → dialog auto-opens → "Import Complete" header →
   no issues sections → "Review imported images" button opens EditGroupDialog → activity
   dock shows "Review import ›" → clicking it reopens ImportDetailsDialog
2. **Import with errors:** Upload valid images + a corrupt file → errors section shows
   with filename, relative path, reason → amber "X imported, Y issues" in dock
3. **Import with upload-phase skips:** Upload includes a .txt file or oversized file →
   "Skipped files" section appears in dialog
4. **Import with Qdrant down:** Stop Qdrant, upload images → warnings section appears →
   images in gallery via FTS → dock shows amber indicator
5. **Failed import:** Server rejects upload → "Import Failed" header → "Cancel & Clean Up"
   button visible
6. **After close:** Close dialog → open dock → click completed-with-issues job →
   ImportDetailsDialog re-opens with same data

---

## Related Files

- `docs/plans/2026-03-04-ingest-error-reporting.md` — original full plan (Stages 1–3)
- `frontend/src/types/index.ts` — `ImportFileError`, `ImportJobResponse`, `ActiveImportJob`
- `frontend/src/components/ImportSummaryDialog.tsx` — starting point for ImportDetailsDialog
- `frontend/src/hooks/useActiveImports.ts` — `failedFiles`/`warningCount` already populated
- `frontend/src/hooks/useImportPolling.ts` — `file_errors` already captured per-group
