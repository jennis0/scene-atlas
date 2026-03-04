# Live Import Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to open `EditGroupDialog` while an import is still processing, see pending groups as non-interactive spinner stubs in the sidebar, and immediately edit any group that finishes.

**Architecture:** A new `useImportReviewPolling` hook polls `/imports/{jobId}/status` to track per-group completion. `EditGroupDialog` gains an `importJobId` prop that activates polling mode: completed groups load incrementally, pending groups render as non-clickable sidebar stubs. `useGalleryDialogs` replaces `importReviewGroupIds` with `importLiveJobId` (a job ID rather than a pre-fetched ID list), and the ActivityDock handler is updated to open `EditGroupDialog` for active (not just completed) import jobs.

**Tech Stack:** React, TypeScript, `@tanstack/react-query` (for cache invalidation), `importApi.status()` for polling, existing `groupApi.get()` for incremental group loading.

**Design doc:** `docs/plans/2026-03-02-live-import-review-design.md`

---

### Task 1: Create `useImportReviewPolling` hook

**Files:**
- Create: `frontend/src/hooks/useImportReviewPolling.ts`

This hook polls `/imports/{importJobId}/status` every 3 seconds. It fires `onGroupCompleted(groupId)` each time a new group transitions to `completed` (only once per group), and sets `allDone` when no groups remain in `running` status.

**Step 1: Create the file**

```typescript
// frontend/src/hooks/useImportReviewPolling.ts
import { useState, useEffect, useRef, useCallback } from 'react'
import { importApi } from '@/lib/api'
import type { ImportGroupStatus } from '@/types'

const POLL_INTERVAL_MS = 3000

interface UseImportReviewPollingOptions {
  importJobId: string | null | undefined
  onGroupCompleted: (groupId: number) => void
  enabled: boolean
}

interface UseImportReviewPollingReturn {
  pendingGroups: ImportGroupStatus[]
  failedGroups: ImportGroupStatus[]
  allDone: boolean
  pollError: boolean
}

export function useImportReviewPolling({
  importJobId,
  onGroupCompleted,
  enabled,
}: UseImportReviewPollingOptions): UseImportReviewPollingReturn {
  const [pendingGroups, setPendingGroups] = useState<ImportGroupStatus[]>([])
  const [failedGroups, setFailedGroups] = useState<ImportGroupStatus[]>([])
  const [allDone, setAllDone] = useState(false)
  const [pollError, setPollError] = useState(false)

  // Tracks which group_ids we've already notified about — prevents double-firing
  const notifiedGroupIds = useRef(new Set<number>())
  const onGroupCompletedRef = useRef(onGroupCompleted)
  onGroupCompletedRef.current = onGroupCompleted

  const poll = useCallback(async () => {
    if (!importJobId) return
    try {
      const status = await importApi.status(importJobId)
      setPollError(false)

      const pending = status.groups.filter((g) => g.status === 'running')
      const failed = status.groups.filter(
        (g) => g.status === 'failed' || g.status === 'cancelled',
      )

      // Fire onGroupCompleted for any newly-completed groups
      for (const g of status.groups) {
        if (g.status === 'completed' && g.group_id && !notifiedGroupIds.current.has(g.group_id)) {
          notifiedGroupIds.current.add(g.group_id)
          onGroupCompletedRef.current(g.group_id)
        }
      }

      setPendingGroups(pending)
      setFailedGroups(failed)
      setAllDone(pending.length === 0)
    } catch {
      setPollError(true)
    }
  }, [importJobId])

  useEffect(() => {
    if (!enabled || !importJobId) {
      setPendingGroups([])
      setFailedGroups([])
      setAllDone(false)
      setPollError(false)
      notifiedGroupIds.current = new Set()
      return
    }

    // Immediate first fetch, then interval
    void poll()
    const id = setInterval(() => void poll(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [enabled, importJobId, poll])

  // Stop polling once done
  useEffect(() => {
    if (allDone) {
      // Nothing to cancel here — the interval effect above will stop
      // re-fetching since poll() only updates state (no side-effects after done).
    }
  }, [allDone])

  return { pendingGroups, failedGroups, allDone, pollError }
}
```

**Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```
Expected: no errors related to the new file.

**Step 3: Commit**

```bash
cd frontend && git add src/hooks/useImportReviewPolling.ts
git commit -m "feat: add useImportReviewPolling hook for live import group status"
```

---

### Task 2: Modify `useEditGroupLoad` for incremental loading

**Files:**
- Modify: `frontend/src/hooks/useEditGroupLoad.ts`

Currently the import-review `useEffect` re-fetches *all* group IDs and replaces the entire `groups` state whenever `groupIds` changes. We need it to only fetch the *new* IDs and append, so in-progress edits on already-loaded groups are not disrupted.

**Step 1: Add a `loadedGroupIdsRef` to the hook**

In `useEditGroupLoad`, find the import-review `useEffect` block (currently starts around line 261 with `if (!open || !isImportReview) return`).

Replace the entire import-review `useEffect` with this implementation:

```typescript
// ── Load: import-review mode (incremental — only fetch newly-added IDs) ──

const loadedGroupIdsRef = useRef(new Set<number>())

// Reset the ref whenever the hook is reset (dialog closes / reopens)
const origResetLoad = useCallback(() => {
  setLoading(false)
  setLoadError(null)
  setUngroupedCount(0)
  setGroups([])
  setActiveTab(0)
  setFileFilter(EMPTY_FILTER)
  setEditingSvHeading(null)
  loadedGroupIdsRef.current = new Set()
}, [setGroups, setActiveTab, setFileFilter, setEditingSvHeading])
```

Wait — `resetLoad` is already defined above in the hook. Instead, amend the existing `resetLoad` definition to also clear `loadedGroupIdsRef`:

In the existing `resetLoad` `useCallback` (around line 123), add `loadedGroupIdsRef.current = new Set()` inside the callback body. The ref is declared just above the callback.

**Step 1 (corrected): Insert `loadedGroupIdsRef` declaration + update `resetLoad`**

After the `[loading, loadError, ungroupedCount]` state declarations (around line 115–117), add:

```typescript
const loadedGroupIdsRef = useRef(new Set<number>())
```

Then in the `resetLoad` `useCallback`, add `loadedGroupIdsRef.current = new Set()` before the last line. The updated callback body:

```typescript
const resetLoad = useCallback(() => {
  setLoading(false)
  setLoadError(null)
  setUngroupedCount(0)
  setGroups([])
  setActiveTab(0)
  setFileFilter(EMPTY_FILTER)
  setEditingSvHeading(null)
  loadedGroupIdsRef.current = new Set()
}, [setGroups, setActiveTab, setFileFilter, setEditingSvHeading])
```

**Step 2: Replace the import-review `useEffect`**

Find the existing block (around line 261):
```typescript
// ── Load: import-review mode (multiple groups by ID, all images in scope) ──

useEffect(() => {
  if (!open || !isImportReview) return
  ...
  setGroups(editableGroups)
  ...
  setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
  ...
}, [open, groupIds, isImportReview, setGroups, setTagVocab, setAuthorSuggestions, setActiveTab])
```

Replace the entire block with:

```typescript
// ── Load: import-review mode (incremental — only fetch newly-added IDs) ──

useEffect(() => {
  if (!open || !isImportReview) return

  const allIds = groupIds ?? []
  const newIds = allIds.filter((id) => !loadedGroupIdsRef.current.has(id))
  if (newIds.length === 0) return

  const isFirstLoad = loadedGroupIdsRef.current.size === 0
  if (isFirstLoad) {
    setLoading(true)
    setLoadError(null)
  }

  Promise.all([
    ...newIds.map((id) => groupApi.get(id)),
    tagApi.getCategories(),
    imageApi.getAuthors(),
  ])
    .then((results) => {
      const groupDetails = results.slice(0, newIds.length) as Awaited<
        ReturnType<typeof groupApi.get>
      >[]
      const categories = results[newIds.length] as Awaited<ReturnType<typeof tagApi.getCategories>>
      const authors = results[newIds.length + 1] as string[]

      const newEditableGroups: EditableGroupState[] = groupDetails.map((detail) => ({
        id: String(detail.id),
        author: detail.author ?? '',
        group_name: detail.base_name,
        files: detail.images.map((img) => imageToEditable(img)),
        skip: false,
        status: 'pending',
        processed: 0,
        failed: 0,
        total: detail.images.length,
      }))

      newIds.forEach((id) => loadedGroupIdsRef.current.add(id))

      setGroups((prev) => [...prev, ...newEditableGroups])
      setTagVocab(parseTagVocabulary(categories))
      setAuthorSuggestions(authors)

      // Only set the active tab on first load
      if (isFirstLoad) {
        setActiveTab(allIds.length > 1 ? ALL_TAB : 0)
      }
    })
    .catch((err: unknown) => {
      setLoadError(getApiErrorMessage(err, 'Failed to load imported groups'))
    })
    .finally(() => {
      if (isFirstLoad) setLoading(false)
    })
}, [open, groupIds, isImportReview, setGroups, setTagVocab, setAuthorSuggestions, setActiveTab])
```

**Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```
Expected: no errors.

**Step 4: Commit**

```bash
cd frontend && git add src/hooks/useEditGroupLoad.ts
git commit -m "feat: incremental group loading in useEditGroupLoad for live import review"
```

---

### Task 3: Update `useGalleryDialogs` — replace `importReviewGroupIds` with `importLiveJobId`

**Files:**
- Modify: `frontend/src/hooks/useGalleryDialogs.ts`

**Step 1: Update the return type interface**

In `UseGalleryDialogsReturn`, replace:
```typescript
// Import review dialog
importReviewGroupIds: number[] | null
setImportReviewGroupIds: (ids: number[] | null) => void
```
With:
```typescript
// Live import review dialog (active or completed job)
importLiveJobId: string | null
setImportLiveJobId: (id: string | null) => void
```

**Step 2: Update the hook implementation**

Replace the state declaration:
```typescript
const [importReviewGroupIds, setImportReviewGroupIds] = useState<number[] | null>(null)
```
With:
```typescript
const [importLiveJobId, setImportLiveJobId] = useState<string | null>(null)
```

**Step 3: Update the return object**

Replace:
```typescript
importReviewGroupIds,
setImportReviewGroupIds,
```
With:
```typescript
importLiveJobId,
setImportLiveJobId,
```

**Step 4: Verify TypeScript compiles (expect errors in Gallery.tsx — that's Task 4)**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules" | head -40
```
Expected: errors in `Gallery.tsx` referencing `importReviewGroupIds` — those will be fixed next.

**Step 5: Commit** (commit even with downstream TS errors — they will be fixed in Task 4)

```bash
cd frontend && git add src/hooks/useGalleryDialogs.ts
git commit -m "refactor: replace importReviewGroupIds with importLiveJobId in useGalleryDialogs"
```

---

### Task 4: Wire up `importLiveJobId` in `Gallery.tsx`

**Files:**
- Modify: `frontend/src/pages/Gallery.tsx`

There are three places to update: (a) the `onJobCompleted` toast handler, (b) the ActivityDock `onOpenJob` handler, and (c) the EditGroupDialog JSX.

**Step 1: Update `importReviewJobIdRef` → `importLiveJobIdRef`**

Find `importReviewJobIdRef` (used to track which job opened the review dialog, so it can be dismissed on save). Rename it to `importLiveJobIdRef` everywhere in the file.

**Step 2: Update the `onJobCompleted` toast handler**

Find the `useEffect` with the "Review" action toast (around line 37-69). It currently does:
```typescript
const status = await importApi.status(jobId)
const ids = status.groups
  .filter((g) => g.group_id != null)
  .map((g) => g.group_id!)
importReviewJobIdRef.current = jobId
dialogs.setImportReviewGroupIds(ids)
```

Replace with:
```typescript
importLiveJobIdRef.current = jobId
dialogs.setImportLiveJobId(jobId)
```

(No need to fetch status upfront — `EditGroupDialog` handles that via polling.)

**Step 3: Update the ActivityDock `onOpenJob` handler**

Find the handler (around line 277-304). Current logic:
```typescript
if (status === 'completed' && pendingGroups === 0) {
  const s = await importApi.status(jobId)
  const ids = s.groups.filter(g => g.group_id).map(g => g.group_id!)
  importReviewJobIdRef.current = jobId
  dialogs.setImportReviewGroupIds(ids)
} else if (status === 'failed' || status === 'broken') {
  dialogs.setImportSummaryJobId(jobId)
} else {
  dialogs.openImportDialog(jobId)
}
```

Replace with:
```typescript
if (status === 'failed' || status === 'broken') {
  dialogs.setImportSummaryJobId(jobId)
} else if (status === 'completed' || status === 'active') {
  importLiveJobIdRef.current = jobId
  dialogs.setImportLiveJobId(jobId)
} else {
  // uploading / staging — reconnect to ImportDialog
  dialogs.openImportDialog(jobId)
}
```

**Step 4: Update the EditGroupDialog (import-review instance) JSX**

Find the EditGroupDialog that renders for import review (around line 193-218). It currently uses `importReviewGroupIds`. Update it to use `importLiveJobId`:

```tsx
{/* Import review EditGroupDialog (live — active or completed import job) */}
<EditGroupDialog
  open={dialogs.importLiveJobId !== null}
  importJobId={dialogs.importLiveJobId ?? undefined}
  onClose={() => dialogs.setImportLiveJobId(null)}
  onSave={() => {
    dialogs.setImportLiveJobId(null)
    if (importLiveJobIdRef.current) {
      activeImports.dismissJob(importLiveJobIdRef.current)
      importLiveJobIdRef.current = null
    }
    dialogs.invalidateGallery()
  }}
/>
```

Note: `groupIds` prop is no longer passed (it was the old import-review mechanism).

**Step 5: Verify TypeScript compiles cleanly**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules" | head -40
```
Expected: no errors.

**Step 6: Commit**

```bash
cd frontend && git add src/pages/Gallery.tsx
git commit -m "feat: open EditGroupDialog for active import jobs via ActivityDock"
```

---

### Task 5: Update `EditGroupDialog` — add `importJobId` prop, polling, pending stubs, footer

**Files:**
- Modify: `frontend/src/components/EditGroupDialog.tsx`

This is the largest change. Work through it section by section.

**Step 1: Add the new prop to the interface**

Find `EditGroupDialogProps` (around line 47). Add:
```typescript
// Live import mode: pass importJobId to enable polling and pending-group stubs
importJobId?: string
```

Also add `importJobId` to the destructured props in the function signature (around line 61):
```typescript
export default function EditGroupDialog({
  groupId,
  seedImages,
  groupIds,
  importJobId,
  open,
  onClose,
  onSave,
}: EditGroupDialogProps) {
```

**Step 2: Add `liveGroupIds` state and polling**

After the `queryClient` declaration (around line 69), add:

```typescript
// ── Live import review state ────────────────────────────────────────────
// Starts from any pre-fetched groupIds; grows as groups complete processing
const [liveGroupIds, setLiveGroupIds] = useState<number[]>(groupIds ?? [])

// Reset liveGroupIds when the dialog closes/opens with a new importJobId
const prevImportJobId = useRef<string | undefined>(undefined)
useEffect(() => {
  if (importJobId !== prevImportJobId.current) {
    prevImportJobId.current = importJobId
    setLiveGroupIds(groupIds ?? [])
  }
}, [importJobId, groupIds])

const { pendingGroups, failedGroups, allDone } = useImportReviewPolling({
  importJobId,
  onGroupCompleted: (groupId) => setLiveGroupIds((prev) => [...prev, groupId]),
  enabled: open && !!importJobId,
})
```

Also add the import at the top of the file:
```typescript
import { useImportReviewPolling } from '@/hooks/useImportReviewPolling'
```

**Step 3: Update `useEditGroupLoad` call to use `liveGroupIds`**

Find the `useEditGroupLoad` call (around line 156). Currently it passes `groupIds` directly. Change it to use `liveGroupIds` when in live import mode:

```typescript
const { loading, loadError, isMassEdit, ungroupedCount } = useEditGroupLoad({
  open,
  groupId,
  seedImages,
  groupIds: importJobId ? (liveGroupIds.length > 0 ? liveGroupIds : undefined) : groupIds,
  onResetDialogState: resetDialogState,
  fileEditing: { ... },
})
```

**Step 4: Update `isImportReview` flag**

Find (around line 174):
```typescript
const isImportReview = !!groupIds && groupIds.length > 0
```

Replace with:
```typescript
const isImportReview = !!importJobId || (!!groupIds && groupIds.length > 0)
```

**Step 5: Update `handleDone` to use `liveGroupIds`**

Find `handleDone` (around line 177). It currently calls `groupApi.confirmReview(groupIds)`. Update it to use `liveGroupIds`:

```typescript
const handleDone = useCallback(() => {
  if (isImportReview) {
    const idsToConfirm = importJobId ? liveGroupIds : (groupIds ?? [])
    onClose()
    groupApi.confirmReview(idsToConfirm).finally(() => {
      onSave()
    })
  } else {
    onSave()
    onClose()
  }
}, [isImportReview, importJobId, liveGroupIds, groupIds, onSave, onClose])
```

**Step 6: Update `isBusy` and footer button gating**

Find (around line 301):
```typescript
const isBusy = saving || groupSaving.size > 0
```

Add below it:
```typescript
const hasPendingGroups = !!importJobId && !allDone
```

Then find the footer "Done" / "Confirm Import" button (around line 762). Update `disabled`:
```typescript
disabled={isBusy || hasPendingGroups}
```

Update the button label to show a "waiting" state:
```typescript
{saving ? (
  <>
    <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
    Working…
  </>
) : groupSaving.size > 0 ? (
  <>
    <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
    Saving…
  </>
) : hasPendingGroups ? (
  `Processing (${pendingGroups.length} remaining…)`
) : isImportReview ? (
  'Confirm Import'
) : (
  'Done'
)}
```

**Step 7: Update the sidebar header count**

Find the `GroupSidebarShell` `headerLabel` prop (around line 364):
```typescript
headerLabel={`${groups.length} groups`}
```

Update to include pending and failed stubs:
```typescript
headerLabel={`${groups.length + pendingGroups.length + failedGroups.length} groups`}
```

**Step 8: Add pending and failed stubs to the sidebar**

Find the end of the `groups.map(...)` block inside `GroupSidebarShell` (around line 499, after the closing `</DroppableGroupRow>`). Add the stubs immediately after the last `</DroppableGroupRow>`:

```tsx
{/* ── Pending group stubs (still processing) ── */}
{pendingGroups.map((stub) => (
  <div
    key={stub.group_job_id}
    className="flex items-center gap-2 pl-3 pr-3 py-2 opacity-60 cursor-not-allowed select-none border-l-2 border-transparent"
  >
    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />
    <span className="flex-1 text-[12px] text-muted-foreground truncate">
      {stub.group_name}
    </span>
    <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
      {stub.processed_files}/{stub.total_files}
    </span>
  </div>
))}

{/* ── Failed group stubs ── */}
{failedGroups.map((stub) => (
  <div
    key={stub.group_job_id}
    className="flex items-center gap-2 pl-3 pr-3 py-2 opacity-70 select-none border-l-2 border-transparent"
  >
    <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
    <span className="flex-1 text-[12px] text-muted-foreground truncate">
      {stub.group_name}
    </span>
    <span className="text-[11px] text-destructive/60 shrink-0">
      {stub.failed_files} failed
    </span>
  </div>
))}
```

`AlertCircle` is already imported at the top of the file.

**Step 9: Handle the loading state when no groups have loaded yet**

Find the loading spinner block (around line 343):
```tsx
{loading && (
  <div className="flex items-center justify-center flex-1">
    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
  </div>
)}
```

The condition is already correct — it shows while `loading` is true. But with incremental loading, we should also show when `liveGroupIds.length === 0 && importJobId && !allDone` and `!loading`:

Add below the existing loading block:
```tsx
{/* Show placeholder while waiting for first group to complete */}
{!loading && !loadError && groups.length === 0 && !!importJobId && !allDone && (
  <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
    <Loader2 className="h-6 w-6 animate-spin" />
    <p className="text-sm">Waiting for groups to process…</p>
  </div>
)}
```

**Step 10: Verify TypeScript compiles cleanly**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules" | head -40
```
Expected: no errors.

**Step 11: Run lint**

```bash
cd frontend && npx eslint src/components/EditGroupDialog.tsx src/hooks/useImportReviewPolling.ts src/hooks/useEditGroupLoad.ts --max-warnings 0
```
Expected: no lint errors.

**Step 12: Commit**

```bash
cd frontend && git add src/components/EditGroupDialog.tsx src/hooks/useImportReviewPolling.ts
git commit -m "feat: add live import review to EditGroupDialog (importJobId prop + pending stubs)"
```

---

### Task 6: Verify end-to-end and clean up

**Step 1: Run all backend tests**

```bash
cd /home/joe/scene-atlas && uv run pytest -x -q
```
Expected: all pass (no backend changes were made, so this is a smoke test).

**Step 2: Full TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules"
```
Expected: clean.

**Step 3: Manual end-to-end verification**

Start the backend and frontend, then:

1. Import a folder with ≥3 sub-folders (so ≥3 groups are created)
2. While `ImportDialog` shows "Processing…" with GroupStatusRow spinners, click the ActivityDock job card
3. Confirm: `EditGroupDialog` opens; all groups appear as spinner stubs in the sidebar
4. Wait for the first group to complete; confirm: it migrates from stub → interactive, you can edit it
5. Confirm: "Confirm Import" button shows "Processing (N remaining…)" and is disabled
6. After all groups finish: confirm "Confirm Import" becomes active
7. Click "Confirm Import" → gallery refreshes, job dismisses from ActivityDock
8. Repeat test opening via the "Review" toast (appears on job completion)
9. Repeat test opening a completed job from ActivityDock

**Step 4: Final commit**

```bash
git add -p  # review any remaining unstaged changes
git commit -m "feat: live import review — edit groups as they complete during import"
```
