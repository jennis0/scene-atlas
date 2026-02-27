# Activity Dock Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the ImportTray with a floating bottom-right Activity Dock that shows all processing jobs (imports, retag, grid detection, vectors, colours) in a compact pill-to-card interface.

**Architecture:** Single new component `ActivityDock` replaces `ImportTray`. Reuses existing hooks (`useActiveImports`, `useBackgroundJobs`) unchanged. Same props interface as ImportTray with minor additions for inline expansion state. The dock is hidden when no jobs exist, shows a collapsed pill when jobs exist, and expands into a card on click.

**Tech Stack:** React, TypeScript, Tailwind CSS, Lucide icons. Vitest + React Testing Library for tests.

**Design doc:** `design/plan-activity-dock.md`
**Visual mockup:** `design/mockup-activity-dock.html`
**Visual language:** `design/visual-language.md`

---

### Task 1: Create ActivityDock component skeleton with pill state

**Files:**
- Create: `frontend/src/components/ActivityDock.tsx`

**Step 1: Create the ActivityDock component with collapsed pill**

Write the full component with the collapsed pill state only. The pill shows when `hasAnything` is true (any import jobs or background jobs). It renders:
- A spinning Loader2 icon when there are active jobs, otherwise a static Package icon
- "Activity" label text
- An amber count badge showing total active count (only when > 0)

```tsx
// frontend/src/components/ActivityDock.tsx
import { useState } from 'react'
import {
  Loader2,
  Package,
  ChevronDown,
  Trash2,
  X,
  Check,
  AlertCircle,
  Clock,
  Ban,
  Upload,
  Cog,
} from 'lucide-react'
import { importApi } from '@/lib/api'
import type { ActiveImportJob } from '@/hooks/useActiveImports'
import type { BackgroundJob } from '@/types'

interface ActivityDockProps {
  jobs: ActiveImportJob[]
  hasActive: boolean
  backgroundJobs: BackgroundJob[]
  hasActiveJobs: boolean
  onOpenJob: (jobId: string) => void
  onDismissJob: (jobId: string) => void
  onCancelJob: (jobId: string) => void
  onRefresh: () => void
}

export function ActivityDock({
  jobs,
  hasActive,
  backgroundJobs,
  hasActiveJobs,
  onOpenJob,
  onDismissJob,
  onCancelJob,
  onRefresh,
}: ActivityDockProps) {
  const [expanded, setExpanded] = useState(false)
  const [cleaning, setCleaning] = useState(false)

  const hasAnything = jobs.length > 0 || backgroundJobs.length > 0
  if (!hasAnything) return null

  const activeImportCount = jobs.filter(
    (j) => j.status === 'staging' || j.status === 'running' || j.pendingGroups > 0,
  ).length
  const activeJobCount = backgroundJobs.filter(
    (j) => j.status === 'queued' || j.status === 'running',
  ).length
  const totalActiveCount = activeImportCount + activeJobCount

  const handleClearHistory = async () => {
    setCleaning(true)
    try {
      await importApi.cleanup()
      onRefresh()
    } finally {
      setCleaning(false)
    }
  }

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="fixed bottom-6 right-6 z-30
          flex items-center gap-2 py-2 px-3.5
          bg-card/95 backdrop-blur-sm
          border border-border/40 rounded-full
          shadow-lg shadow-black/40
          transition-all duration-200
          hover:bg-secondary hover:border-border/60
          hover:shadow-xl hover:shadow-black/50
          hover:-translate-y-px"
        title={
          totalActiveCount > 0
            ? `${totalActiveCount} active task${totalActiveCount !== 1 ? 's' : ''}`
            : 'Activity'
        }
      >
        {totalActiveCount > 0 ? (
          <Loader2 className="h-4 w-4 text-primary animate-spin" />
        ) : (
          <Package className="h-4 w-4 text-primary" />
        )}
        <span className="text-[12px] font-medium text-muted-foreground">Activity</span>
        {totalActiveCount > 0 && (
          <span className="min-w-[18px] h-[18px] flex items-center justify-center
            rounded-full bg-primary text-primary-foreground
            text-[10px] font-bold tabular-nums leading-none px-1">
            {totalActiveCount}
          </span>
        )}
      </button>
    )
  }

  // Expanded card — Task 2 will fill this in
  return (
    <div className="fixed bottom-6 right-6 z-30">
      <div className="w-[320px] text-sm text-muted-foreground bg-card rounded-xl border border-border/30 shadow-2xl shadow-black/60 overflow-hidden">
        <div className="p-4">Expanded card placeholder</div>
      </div>
    </div>
  )
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors (or only pre-existing ones)

**Step 3: Commit**

```bash
git add frontend/src/components/ActivityDock.tsx
git commit -m "feat: add ActivityDock component skeleton with collapsed pill"
```

---

### Task 2: Implement the expanded card shell (header, footer, scroll area)

**Files:**
- Modify: `frontend/src/components/ActivityDock.tsx`

**Step 1: Replace the expanded card placeholder with the full card shell**

The expanded card has:
- Click-away overlay (fixed inset-0 div behind the card)
- Amber stripe at top
- Header: Cinzel "Activity" title, amber rule, "N active" badge, clear + collapse buttons
- Scrollable job list area (empty for now)
- Footer: hint text + job count
- Escape key handler to collapse

Replace the `// Expanded card — Task 2 will fill this in` return block:

```tsx
  return (
    <>
      {/* Click-away overlay */}
      <div className="fixed inset-0 z-20" onClick={() => setExpanded(false)} />

      <div className="fixed bottom-6 right-6 z-30">
        <div
          className="w-[320px] flex flex-col bg-card rounded-xl border border-border/30
            shadow-2xl shadow-black/60 overflow-hidden"
          style={{ maxHeight: 'min(520px, 65vh)' }}
        >
          {/* Amber stripe */}
          <div className="h-0.5 shrink-0 bg-gradient-to-r from-transparent to-primary/70" />

          {/* Header */}
          <div className="px-3.5 pt-2.5 shrink-0">
            <div className="flex items-center justify-between">
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <span className="font-display text-[13px] font-medium tracking-[0.06em] text-foreground leading-none">
                    Activity
                  </span>
                  {totalActiveCount > 0 && (
                    <span className="inline-flex items-center px-1.5 py-px rounded-full bg-primary/15 text-[10px] font-medium text-primary tabular-nums">
                      {totalActiveCount} active
                    </span>
                  )}
                </div>
                <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
              </div>
              <div className="flex items-center gap-0.5">
                {terminalCount > 0 && (
                  <button
                    onClick={handleClearHistory}
                    disabled={cleaning}
                    className="h-7 w-7 rounded flex items-center justify-center
                      text-muted-foreground hover:text-destructive hover:bg-destructive/10
                      transition-colors disabled:opacity-30"
                    title="Clear completed"
                  >
                    {cleaning ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
                <button
                  onClick={() => setExpanded(false)}
                  className="h-7 w-7 rounded flex items-center justify-center
                    text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                  title="Collapse"
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>

          {/* Divider */}
          <div className="mx-3.5 mt-2 h-px bg-border/40 shrink-0" />

          {/* Scrollable job list */}
          <div className="flex-1 min-h-0 overflow-y-auto py-2 px-2 space-y-1.5">
            {/* Job cards — Task 3 */}
          </div>

          {/* Footer */}
          <div className="px-3.5 py-[7px] border-t border-border/30 shrink-0 flex items-center justify-between"
            style={{ background: 'hsl(var(--popover))' }}>
            <span className="text-[10.5px] text-muted-foreground/50 italic">
              Click imports to open dialog
            </span>
            <span className="text-[10.5px] text-muted-foreground/40 tabular-nums">
              {jobs.length + backgroundJobs.length} jobs
            </span>
          </div>
        </div>
      </div>
    </>
  )
```

Also add `terminalCount` computation alongside the other counts:

```tsx
const terminalCount =
  jobs.filter(
    (j) => j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled',
  ).length +
  backgroundJobs.filter((j) => j.status === 'completed' || j.status === 'failed').length
```

Add an Escape key handler via `useEffect`:

```tsx
import { useState, useEffect } from 'react'

// Inside the component, after the expanded state:
useEffect(() => {
  if (!expanded) return
  const handleKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') setExpanded(false)
  }
  window.addEventListener('keydown', handleKey)
  return () => window.removeEventListener('keydown', handleKey)
}, [expanded])
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/ActivityDock.tsx
git commit -m "feat: add expanded card shell with header, footer, and scroll area"
```

---

### Task 3: Implement job card sub-components

**Files:**
- Modify: `frontend/src/components/ActivityDock.tsx`

**Step 1: Add the ImportJobCard sub-component**

Add after the main `ActivityDock` export:

```tsx
function ImportJobCard({
  job,
  onOpen,
  onDismiss,
  onCancel,
}: {
  job: ActiveImportJob
  onOpen: () => void
  onDismiss: () => void
  onCancel: () => void
}) {
  const isTerminal =
    job.status === 'completed' ||
    job.status === 'failed' ||
    job.status === 'cancelled' ||
    job.status === 'expired'
  const canCancel =
    job.status === 'uploading' || job.status === 'staging' || job.status === 'active'
  const effectiveTotal =
    job.totalGroups > 0
      ? job.totalGroups
      : job.pendingGroups + job.completedGroups + job.failedGroups + job.runningGroups
  const progressRatio = effectiveTotal > 0 ? job.completedGroups / effectiveTotal : 0

  return (
    <div
      className={`group/job rounded-md border transition-colors cursor-pointer ${
        isTerminal
          ? 'border-border/15 bg-muted/10 opacity-75 hover:opacity-100'
          : 'border-border/30 bg-secondary/20 hover:bg-secondary/40 hover:border-border/50'
      }`}
      onClick={onOpen}
    >
      <div className="px-2.5 py-2">
        {/* Top row */}
        <div className="flex items-start gap-[7px]">
          <ImportStatusIcon status={job.status} />
          <span
            className={`flex-1 text-[12px] font-medium truncate leading-tight ${
              isTerminal ? 'text-muted-foreground' : 'text-foreground'
            }`}
          >
            {job.label}
            {!isTerminal && (
              <span className="ml-1.5 text-muted-foreground/25 text-[13px] transition-all group-hover/job:text-primary/60 group-hover/job:ml-2">
                ›
              </span>
            )}
          </span>
          {isTerminal && (
            <button
              onClick={(e) => { e.stopPropagation(); onDismiss() }}
              className="opacity-0 group-hover/job:opacity-100 shrink-0
                h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/30 hover:text-foreground hover:bg-secondary transition-all"
              title="Dismiss"
            >
              <X className="h-3 w-3" />
            </button>
          )}
          {canCancel && (
            <button
              onClick={(e) => { e.stopPropagation(); onCancel() }}
              className="opacity-0 group-hover/job:opacity-100 shrink-0
                h-5 w-5 rounded flex items-center justify-center
                text-muted-foreground/30 hover:text-destructive hover:bg-destructive/10 transition-all"
              title="Cancel"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Progress bar */}
        <div className="flex items-center gap-2 mt-[7px]">
          <div className="flex-1 h-[3px] rounded-full bg-border/30 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ease-out ${
                job.status === 'failed'
                  ? 'bg-destructive/55'
                  : isTerminal
                    ? 'bg-primary/45'
                    : 'bg-primary/70'
              }`}
              style={{ width: `${Math.round(progressRatio * 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-muted-foreground/55 tabular-nums shrink-0">
            {job.completedGroups}/{effectiveTotal}
          </span>
        </div>

        {/* Status summary */}
        <div className="mt-1 text-[10px] text-muted-foreground/45 leading-tight">
          <ImportStatusText job={job} />
        </div>
      </div>
    </div>
  )
}
```

**Step 2: Add the BackgroundJobCard sub-component with inline expansion**

```tsx
function BackgroundJobCard({ job }: { job: BackgroundJob }) {
  const [expanded, setExpanded] = useState(false)
  const isTerminal = job.status === 'completed' || job.status === 'failed'
  const pct = job.progress_pct ?? 0

  return (
    <div
      className={`group/job rounded-md border transition-colors cursor-pointer ${
        isTerminal
          ? `border-border/15 bg-muted/10 ${expanded ? 'opacity-100' : 'opacity-75 hover:opacity-100'}`
          : 'border-border/30 bg-secondary/20 hover:bg-secondary/40'
      } ${expanded && isTerminal && job.status === 'failed' ? 'border-destructive/15 bg-destructive/[0.03]' : ''}`}
      onClick={() => isTerminal && setExpanded(!expanded)}
    >
      <div className="px-2.5 py-2">
        <div className="flex items-start gap-[7px]">
          <JobStatusIcon status={job.status} />
          <span
            className={`flex-1 text-[12px] font-medium truncate leading-tight ${
              isTerminal && !expanded ? 'text-muted-foreground' : 'text-foreground'
            }`}
          >
            {job.name}
          </span>
          {job.progress_pct != null && !isTerminal && (
            <span className="text-[10px] text-muted-foreground/55 tabular-nums shrink-0">
              {pct}%
            </span>
          )}
          {expanded && (
            <ChevronDown className="h-3 w-3 text-muted-foreground/40 shrink-0 mt-0.5 rotate-180" />
          )}
        </div>

        {/* Progress bar */}
        {(job.status === 'running' || job.status === 'queued' || isTerminal) && (
          <div className="flex items-center gap-2 mt-[7px]">
            <div className="flex-1 h-[3px] rounded-full bg-border/30 overflow-hidden">
              {job.status === 'queued' ? (
                <div className="h-full w-full bg-muted-foreground/15 animate-pulse" />
              ) : (
                <div
                  className={`h-full rounded-full transition-all duration-700 ease-out ${
                    job.status === 'failed' ? 'bg-destructive/55' : isTerminal ? 'bg-primary/45' : 'bg-primary/70'
                  }`}
                  style={{ width: `${isTerminal && job.status !== 'failed' ? 100 : pct}%` }}
                />
              )}
            </div>
            {job.progress_current != null && job.progress_total != null && (
              <span className="text-[10px] text-muted-foreground/55 tabular-nums shrink-0">
                {job.progress_current}/{job.progress_total}
              </span>
            )}
          </div>
        )}

        {/* Status text */}
        <div className="mt-1 text-[10px] text-muted-foreground/45 leading-tight">
          {job.status === 'queued' && <span>Queued</span>}
          {job.status === 'running' && <span>{job.progress ?? 'Processing...'}</span>}
          {job.status === 'completed' && <span>{formatResult(job.result)}</span>}
          {job.status === 'failed' && (
            <span className="text-destructive/65">{expanded ? 'Failed' : (job.error ?? 'Failed')}</span>
          )}
        </div>

        {/* Inline expansion for terminal jobs */}
        {expanded && isTerminal && (
          <div className="mt-1.5 pt-1.5 border-t border-dashed border-border/30">
            {job.status === 'completed' && job.result && (
              <div className="space-y-0.5">
                {Object.entries(job.result).map(([key, val]) => (
                  <div key={key} className="flex justify-between text-[10px]">
                    <span className="text-muted-foreground/35 font-medium uppercase tracking-[0.08em]">
                      {key.replace(/_/g, ' ')}
                    </span>
                    <span className="text-muted-foreground/55 tabular-nums">{String(val)}</span>
                  </div>
                ))}
              </div>
            )}
            {job.status === 'failed' && job.error && (
              <div className="flex justify-between text-[10px] gap-4">
                <span className="text-muted-foreground/35 font-medium uppercase tracking-[0.08em] shrink-0">
                  Error
                </span>
                <span className="text-destructive/65 text-right">{job.error}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

Note: `BackgroundJob` type doesn't have `progress_current`/`progress_total` fields — those are `progress_pct` and the raw values come as part of `progress` string. Check the type and use what's available. If only `progress_pct` exists, show percentage in the counts area instead. The plan code above is illustrative — adapt to the actual `BackgroundJob` type which has: `id, name, status, submitted_at, started_at, finished_at, progress, progress_pct, result, error`.

**Step 3: Add the status icon helpers and status text helper**

```tsx
function ImportStatusIcon({ status }: { status: ActiveImportJob['status'] }) {
  switch (status) {
    case 'uploading':
      return <Upload className="h-3.5 w-3.5 text-primary animate-pulse shrink-0 mt-0.5" />
    case 'running':
    case 'active':
      return <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'completed':
      return <Check className="h-3.5 w-3.5 text-primary/60 shrink-0 mt-0.5" />
    case 'failed':
      return <AlertCircle className="h-3.5 w-3.5 text-destructive/70 shrink-0 mt-0.5" />
    case 'cancelled':
      return <Ban className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0 mt-0.5" />
    case 'expired':
    case 'staging':
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 mt-0.5" />
  }
}

function JobStatusIcon({ status }: { status: BackgroundJob['status'] }) {
  switch (status) {
    case 'running':
      return <Cog className="h-3.5 w-3.5 text-primary animate-spin shrink-0 mt-0.5" />
    case 'completed':
      return <Check className="h-3.5 w-3.5 text-primary/60 shrink-0 mt-0.5" />
    case 'failed':
      return <AlertCircle className="h-3.5 w-3.5 text-destructive/70 shrink-0 mt-0.5" />
    case 'queued':
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 mt-0.5" />
  }
}

function ImportStatusText({ job }: { job: ActiveImportJob }) {
  switch (job.status) {
    case 'uploading':
      return <span>Uploading…</span>
    case 'staging':
      return <span>{job.pendingGroups} group{job.pendingGroups !== 1 ? 's' : ''} ready to review</span>
    case 'running':
    case 'active': {
      const parts: string[] = []
      if (job.runningGroups > 0) parts.push(`${job.runningGroups} processing`)
      if (job.completedGroups > 0) parts.push(`${job.completedGroups} imported`)
      if (job.pendingGroups > 0) parts.push(`${job.pendingGroups} pending`)
      return <span>{parts.length > 0 ? parts.join(', ') : 'Processing…'}</span>
    }
    case 'completed':
      return <span>{job.completedGroups} group{job.completedGroups !== 1 ? 's' : ''} imported</span>
    case 'failed':
      return (
        <span className="text-destructive/65">
          {job.failedGroups} failed{job.completedGroups > 0 ? `, ${job.completedGroups} completed` : ''}
        </span>
      )
    case 'cancelled':
      return <span>Cancelled</span>
    case 'expired':
      return <span>Expired</span>
    default:
      return null
  }
}

function formatResult(result: Record<string, unknown> | null): string {
  if (!result) return 'Done'
  if ('succeeded' in result && 'failed' in result) {
    const failed = result.failed as number
    return failed > 0
      ? `${result.succeeded} succeeded, ${failed} failed`
      : `${result.succeeded} images processed`
  }
  if ('tags_created' in result) return `${result.tags_created} tags created`
  return 'Done'
}
```

**Step 4: Wire the job cards into the scrollable list**

In the expanded card's `{/* Job cards — Task 3 */}` slot:

```tsx
{/* Import jobs */}
{jobs.map((job) => (
  <ImportJobCard
    key={job.jobId}
    job={job}
    onOpen={() => onOpenJob(job.jobId)}
    onDismiss={() => onDismissJob(job.jobId)}
    onCancel={() => onCancelJob(job.jobId)}
  />
))}

{/* Section divider — only when both active and background jobs exist */}
{jobs.length > 0 && backgroundJobs.length > 0 && (
  <div className="flex items-center gap-2 pt-1.5 pb-0.5">
    <div className="h-px flex-1 bg-border/30" />
    <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/40 shrink-0">
      Jobs
    </span>
    <div className="h-px flex-1 bg-border/30" />
  </div>
)}

{/* Background jobs */}
{backgroundJobs.map((job) => (
  <BackgroundJobCard key={job.id} job={job} />
))}
```

**Step 5: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 6: Commit**

```bash
git add frontend/src/components/ActivityDock.tsx
git commit -m "feat: add import and background job card sub-components"
```

---

### Task 4: Write tests for ActivityDock

**Files:**
- Create: `frontend/src/components/ActivityDock.test.tsx`

**Step 1: Write tests covering key behaviors**

Test the following scenarios:
1. **Hidden when no jobs** — renders nothing when both lists are empty
2. **Shows pill when jobs exist** — renders pill with "Activity" text
3. **Shows active count badge** — pill shows count when active jobs exist
4. **No badge when idle** — pill shows no badge when only terminal jobs exist
5. **Expands on pill click** — clicking pill shows expanded card
6. **Shows import job cards** — expanded card shows import job labels
7. **Shows background job cards** — expanded card shows background job names
8. **Click-away collapses** — clicking overlay collapses to pill
9. **Import card fires onOpenJob** — clicking import card calls callback

```tsx
// frontend/src/components/ActivityDock.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ActivityDock } from './ActivityDock'
import type { ActiveImportJob } from '@/hooks/useActiveImports'
import type { BackgroundJob } from '@/types'

vi.mock('@/lib/api', () => ({
  importApi: { cleanup: vi.fn().mockResolvedValue(undefined) },
}))

const baseProps = {
  jobs: [] as ActiveImportJob[],
  hasActive: false,
  backgroundJobs: [] as BackgroundJob[],
  hasActiveJobs: false,
  onOpenJob: vi.fn(),
  onDismissJob: vi.fn(),
  onCancelJob: vi.fn(),
  onRefresh: vi.fn(),
}

const runningImport: ActiveImportJob = {
  jobId: 'imp-1',
  label: 'Dark Forest Maps',
  status: 'running',
  totalGroups: 8,
  completedGroups: 3,
  failedGroups: 0,
  runningGroups: 2,
  pendingGroups: 3,
  totalFiles: 24,
  createdAt: new Date().toISOString(),
  localOnly: false,
}

const completedImport: ActiveImportJob = {
  ...runningImport,
  jobId: 'imp-2',
  label: 'Coastal Ruins',
  status: 'completed',
  completedGroups: 4,
  totalGroups: 4,
  runningGroups: 0,
  pendingGroups: 0,
}

const runningBgJob: BackgroundJob = {
  id: 'bg-1',
  name: 'Regenerate Auto-Tags',
  status: 'running',
  submitted_at: new Date().toISOString(),
  started_at: new Date().toISOString(),
  finished_at: null,
  progress: 'Processing tags...',
  progress_pct: 47,
  result: null,
  error: null,
}

describe('ActivityDock', () => {
  it('renders nothing when no jobs exist', () => {
    const { container } = renderWithProviders(<ActivityDock {...baseProps} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows pill with Activity text when jobs exist', () => {
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[runningImport]} hasActive />,
    )
    expect(screen.getByText('Activity')).toBeInTheDocument()
  })

  it('shows active count badge on pill', () => {
    renderWithProviders(
      <ActivityDock
        {...baseProps}
        jobs={[runningImport]}
        hasActive
        backgroundJobs={[runningBgJob]}
        hasActiveJobs
      />,
    )
    // 1 running import + 1 running background = 2
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('hides badge when only terminal jobs exist', () => {
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[completedImport]} />,
    )
    expect(screen.getByText('Activity')).toBeInTheDocument()
    expect(screen.queryByText('1')).not.toBeInTheDocument()
  })

  it('expands on pill click to show card', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock {...baseProps} jobs={[runningImport]} hasActive />,
    )
    await user.click(screen.getByText('Activity'))
    expect(screen.getByText('Dark Forest Maps')).toBeInTheDocument()
  })

  it('shows background job names in expanded card', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock
        {...baseProps}
        backgroundJobs={[runningBgJob]}
        hasActiveJobs
      />,
    )
    await user.click(screen.getByText('Activity'))
    expect(screen.getByText('Regenerate Auto-Tags')).toBeInTheDocument()
  })

  it('calls onOpenJob when clicking import card', async () => {
    const onOpenJob = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(
      <ActivityDock
        {...baseProps}
        jobs={[runningImport]}
        hasActive
        onOpenJob={onOpenJob}
      />,
    )
    await user.click(screen.getByText('Activity'))
    await user.click(screen.getByText('Dark Forest Maps'))
    expect(onOpenJob).toHaveBeenCalledWith('imp-1')
  })
})
```

**Step 2: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ActivityDock.test.tsx`
Expected: All tests pass

**Step 3: Commit**

```bash
git add frontend/src/components/ActivityDock.test.tsx
git commit -m "test: add ActivityDock component tests"
```

---

### Task 5: Replace ImportTray with ActivityDock in Gallery

**Files:**
- Modify: `frontend/src/pages/Gallery.tsx` (lines ~26 and ~783)

**Step 1: Update the import statement**

In `frontend/src/pages/Gallery.tsx`, find:
```tsx
import { ImportTray } from '@/components/ImportTray'
```
Replace with:
```tsx
import { ActivityDock } from '@/components/ActivityDock'
```

**Step 2: Replace the JSX usage**

Find the `<ImportTray` block (around line 783) and replace `ImportTray` with `ActivityDock`. The props interface is identical, so it's a direct rename:

```tsx
{/* Activity dock — bottom-right floating panel showing all jobs */}
<ActivityDock
  jobs={activeImports.jobs}
  hasActive={activeImports.hasActive}
  backgroundJobs={backgroundJobs.jobs}
  hasActiveJobs={backgroundJobs.hasActive}
  onOpenJob={(jobId) => {
    // ... existing onOpenJob logic stays exactly the same
  }}
  onDismissJob={activeImports.dismissJob}
  onCancelJob={activeImports.cancelJob}
  onRefresh={activeImports.refresh}
/>
```

**Step 3: Verify it compiles and existing tests pass**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: No type errors, all tests pass

**Step 4: Commit**

```bash
git add frontend/src/pages/Gallery.tsx
git commit -m "feat: replace ImportTray with ActivityDock in Gallery"
```

---

### Task 6: Manual visual verification and polish

**Files:**
- Possibly modify: `frontend/src/components/ActivityDock.tsx`

**Step 1: Run the dev server and visually verify**

Run: `cd frontend && npm run dev`

Test the following manually:
1. Start with no jobs — dock should be hidden
2. Trigger an import — pill should appear with count badge
3. Click pill — card should expand with the import job
4. Click the import job card — should open import dialog
5. Trigger a retag from Tag Management — background job should appear
6. Click a completed background job — should expand inline
7. Click outside the card — should collapse to pill
8. Press Escape — should collapse to pill

**Step 2: Adjust any visual issues**

Compare against the mockup at `design/mockup-activity-dock.html`. Common things to check:
- Spacing and padding match the mockup
- Progress bar height is 3px
- Font sizes match (12px labels, 10px status/counts)
- Amber stripe renders correctly
- Terminal job opacity (75% default, 100% on hover)
- Scroll behavior works when many jobs exist

**Step 3: Commit any polish**

```bash
git add frontend/src/components/ActivityDock.tsx
git commit -m "style: polish ActivityDock visual alignment with mockup"
```

---

### Task 7: Update visual language doc with dock pattern

**Files:**
- Modify: `design/visual-language.md`

**Step 1: Add the Dock Pattern section**

Add a new section after "## Shared Interactive Components" (around line 400) documenting the dock pattern for future reference:

```markdown
### ActivityDock (`frontend/src/components/ActivityDock.tsx`)
Floating bottom-right card for viewing background job status.

**Collapsed pill:** `bg-card/95 backdrop-blur-sm border border-border/40 rounded-full shadow-lg shadow-black/40`. Hover: `bg-secondary hover:-translate-y-px`. Shows Loader2 (spinning) when active, Package when idle. Active count badge uses the solid tier.

**Expanded card:** `w-[320px] max-h-[min(520px,65vh)] bg-card rounded-xl border border-border/30 shadow-2xl shadow-black/60`. Amber stripe at top. Header follows panel header pattern (Cinzel title + amber rule). Footer uses `bg-popover`.

**Job cards:** `rounded-md border-border/30 bg-secondary/20 hover:bg-secondary/40`. Terminal: `opacity-75 hover:opacity-100`. Progress: 3px track.

**Visibility:** Hidden when no jobs exist. No auto-expand — user clicks pill to open.
```

**Step 2: Commit**

```bash
git add design/visual-language.md
git commit -m "docs: add dock pattern to visual language reference"
```

---

### Task 8: Delete ImportTray (cleanup)

**Files:**
- Delete: `frontend/src/components/ImportTray.tsx`

**Step 1: Verify ImportTray is no longer imported anywhere**

Search for any remaining references:
```bash
grep -r "ImportTray" frontend/src/ --include="*.ts" --include="*.tsx"
```

Expected: No results (if Task 5 was done correctly). If any references remain, update them.

**Step 2: Delete the file**

```bash
rm frontend/src/components/ImportTray.tsx
```

**Step 3: Verify build still works**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: No errors

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove ImportTray, fully replaced by ActivityDock"
```
