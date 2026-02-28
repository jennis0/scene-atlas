# Activity Dock — Design Document

**Date:** 2026-02-27
**Replaces:** ImportTray component
**Mockup:** `design/mockup-activity-dock.html`

---

## Summary

A floating bottom-right activity dock that replaces the existing ImportTray. Shows status of all processing jobs (imports, retag, grid detection, vector rebuilds, colour palette updates) in a compact card anchored to the bottom-right corner.

## Architecture

### Component: `ActivityDock`

**Position:** Fixed, bottom-right (`bottom: 24px, right: 24px`), z-index 30.

**Two states:**
1. **Collapsed pill** — small rounded pill showing an activity icon + active job count badge
2. **Expanded card** — 320px wide card that grows upward from the pill position

**Visibility:** The dock is hidden entirely when no jobs exist (no active, no recent). It appears when a job is submitted and disappears when the last job is dismissed or ages out.

### States

| State | Trigger | Appearance |
|-------|---------|------------|
| Hidden | No jobs in session | Nothing rendered |
| Collapsed (active) | Jobs exist, user collapsed or default | Pill with spinning icon + count badge |
| Collapsed (idle) | Only completed/failed jobs remain | Pill with static icon, no badge |
| Expanded | User clicks pill | Full card with job list |

**No auto-expand.** The pill appears with the count badge; the user opens it themselves. This avoids disrupting workflow.

### Job Types

| Type | Source | Click Action | Cancel |
|------|--------|-------------|--------|
| Import | `useActiveImports` hook | Opens import dialog | Yes (POST /imports/{id}/cancel) |
| Retag | `useBackgroundJobs` hook | Expand inline | Not yet (future) |
| Grid Detection | `useBackgroundJobs` hook | Expand inline | Not yet |
| Vector Rebuild | `useBackgroundJobs` hook | Expand inline | Not yet |
| Colour Palettes | `useBackgroundJobs` hook | Expand inline | Not yet |

### Job Card Design

Each job is a card row within the scrollable list. Two visual variants:

**Import jobs:** Show group-level progress (e.g. "3/8 groups, 2 processing, 3 pending"). A subtle `›` indicator signals they're clickable (opens the import dialog).

**Background jobs:** Show overall progress (e.g. "142/300, Processing tags..."). Clicking expands inline to show result details or error information. No navigation.

### Card States

| State | Icon | Progress | Text Color |
|-------|------|----------|------------|
| Running | Spinner (amber) | Amber fill | foreground |
| Queued | Clock (muted) | Pulsing indeterminate | foreground |
| Completed | Check (amber/60) | Full, muted amber | muted-foreground |
| Failed | AlertCircle (destructive) | Partial, destructive | muted-foreground |
| Cancelled | Ban (muted) | Stopped | muted-foreground |
| Staging | Clock (amber/50) | N/A | foreground |

Terminal jobs (completed, failed, cancelled) render at 75% opacity with muted borders. Hovering restores full opacity.

### Inline Expansion (Background Jobs)

When a background job card is clicked, it expands to show:
- **Result summary** (for completed jobs, e.g. "847 tags assigned")
- **Error details** (for failed jobs, e.g. "Connection timeout — CUDA out of memory")

The expansion uses a dashed divider inside the card. A chevron-up indicator shows it's expanded. Clicking again collapses it.

### Active/Recent Divider

A horizontal ruled divider with the label "Recent" separates active jobs from completed/failed ones. Only shown when both active and recent jobs exist.

### History

Session-only. Completed jobs remain visible until:
- The user dismisses them individually (× button on hover)
- The user clicks "Clear completed" in the header
- The browser session ends

This matches the backend's 1-hour retention policy — no persistent history beyond what the backend keeps in memory.

### Interactions

| Action | Result |
|--------|--------|
| Click pill | Expand card |
| Click outside card | Collapse to pill |
| Click chevron-down in header | Collapse to pill |
| Click import job card | Calls `onOpenJob(jobId)` — opens import dialog |
| Click background job card | Toggle inline expansion |
| Hover terminal job → click × | Dismiss from session |
| Hover active import → click × | Cancel import (with confirmation?) |
| Click trash icon in header | Clear all completed/failed jobs |
| Escape key (when card focused) | Collapse to pill |

## Visual Language

Follows existing design tokens from `visual-language.md`. Establishes the "dock" pattern variant:

### Dock Pattern (new to visual language)

```
Collapsed pill:
  bg-card/95 backdrop-blur-sm border border-border/40 rounded-full
  shadow-lg shadow-black/40
  Hover: bg-secondary, translateY(-1px)

Expanded card:
  bg-card border border-border/30 rounded-xl
  shadow-2xl shadow-black/60
  Width: 320px, max-height: min(520px, 65vh)

Header:
  font-display text-[13px] title + panel-level amber rule
  "N active" tinted badge (bg-primary/15 text-primary)

Footer:
  bg-popover, border-t border-border/30
  Hint text (italic, muted) + count

Amber stripe: gradient from transparent to primary/70 (right-aligned, matches sidebar pattern)
```

### Job Card Tokens

| Element | Classes |
|---------|---------|
| Card (active) | `rounded-md border border-border/30 bg-secondary/20 hover:bg-secondary/40` |
| Card (terminal) | `rounded-md border border-border/15 bg-muted/10 opacity-75 hover:opacity-100` |
| Label | `text-[12px] font-medium` |
| Progress track | `h-[3px] rounded-full bg-border/30` |
| Progress fill (running) | `bg-primary/70` |
| Progress fill (completed) | `bg-primary/45` |
| Progress fill (failed) | `bg-destructive/55` |
| Status text | `text-[10px] text-muted-foreground/45` |
| Counts | `text-[10px] tabular-nums text-muted-foreground/55` |

## Data Flow

```
useActiveImports() ──┐
                     ├──→ ActivityDock component
useBackgroundJobs() ─┘

Props:
  importJobs: ActiveImportJob[]
  backgroundJobs: BackgroundJob[]
  hasActive: boolean
  onOpenJob: (jobId: string) => void
  onDismissJob: (jobId: string) => void
  onCancelJob: (jobId: string) => void
  onRefresh: () => void
```

The component merges both job sources into a unified list, sorted: active first (by start time), then recent (by completion time, newest first).

## Implementation Notes

- Replaces `ImportTray.tsx` — same props interface, different presentation
- Reuse existing hooks (`useActiveImports`, `useBackgroundJobs`) without modification
- The parent component (likely `App.tsx` or `GalleryPage.tsx`) that currently renders `<ImportTray>` switches to `<ActivityDock>`
- Click-away uses a fixed overlay div (same pattern as current ImportTray)
- Transition between collapsed/expanded uses CSS `transition-all duration-300`
