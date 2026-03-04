# Dialog UX Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Five targeted UX improvements to ImportDialog and EditGroupDialog for better usability at scale.

**Architecture:** All changes are frontend-only. Tasks 1, 4, 5 touch shared components used by both dialogs. Task 2 creates a new local-data merge picker for imports. Task 3 adds a button to an existing component.

**Tech Stack:** React, TypeScript, Tailwind CSS, lucide-react icons, Radix UI (dropdown menus, dialogs)

---

### Task 1: Click-to-select thumbnails + magnify icon for preview

**Problem:** Clicking the thumbnail opens the lightbox. With smaller cards, users expect click to select, not preview.

**Files:**
- Modify: `frontend/src/components/import/shared/FileCardThumbnail.tsx`

**Step 1: Modify FileCardThumbnail**

Change the `<button>` wrapper to a `<div>`. This causes thumbnail clicks to bubble up to the parent card's `onClick={handleCardClick}`, which calls `onToggleSelect()` (the parent already skips clicks on `button` and `[data-no-select]` elements, so the new magnify button won't trigger selection).

Add a ZoomIn icon button overlay in the top-right corner (matching the checkbox overlay style in the top-left).

```tsx
import { ZoomIn } from 'lucide-react'

// ... inside FileCardThumbnail props: no changes needed (onOpenLightbox stays)

// Replace the <button> wrapper with <div>:
<div
  className={`${cls} shrink-0 relative overflow-hidden rounded-l-lg bg-secondary min-h-[80px]`}
  style={{ filter }}
>
  {/* ... existing image/video content unchanged ... */}

  {/* Selection checkbox overlay — unchanged */}
  {!dimmed && !hideCheckbox && (
    <div className={`absolute top-1.5 left-1.5 ...`}>✓</div>
  )}

  {/* NEW: Magnify icon overlay — top-right, visible on hover */}
  {previewUrl && !dimmed && (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onOpenLightbox()
      }}
      className="absolute top-1.5 right-1.5 w-5 h-5 rounded-[3px] flex items-center justify-center bg-black/40 border-[1.5px] border-white/20 text-white/70 opacity-0 group-hover/card:opacity-100 hover:bg-black/60 hover:text-white transition-all backdrop-blur-sm cursor-zoom-in"
      tabIndex={-1}
    >
      <ZoomIn className="h-3 w-3" />
    </button>
  )}
</div>
```

**Step 2: Verify both dialogs work**

Run the dev server and test:
- ImportDialog: click thumbnail → card selects (not lightbox). Click magnify icon → lightbox opens.
- EditGroupDialog: same behavior.
- Excluded/dimmed cards: magnify icon hidden (dimmed check), but lightbox not broken.
- Out-of-scope cards: thumbnail click does nothing (no handleCardClick on parent). Magnify icon still hidden (dimmed=true).

**Step 3: Commit**

```bash
git add frontend/src/components/import/shared/FileCardThumbnail.tsx
git commit -m "feat: click thumbnail to select card, add magnify icon for preview"
```

---

### Task 2: ImportMergeGroupPicker for local import groups

**Problem:** The `...` dropdown in ImportGroupNav lists all other groups inline — no scrolling, unusable with many groups.

**Solution:** Create a lightweight `ImportMergeGroupPicker` that takes local `EditableGroupState[]` groups (not API-fetched), provides client-side search, and returns the selected group index. Visually mirrors `MergeGroupPicker`.

**Files:**
- Create: `frontend/src/components/import/ImportMergeGroupPicker.tsx`
- Modify: `frontend/src/components/import/ImportGroupNav.tsx`

**Step 1: Create ImportMergeGroupPicker**

A dialog with a search input and scrollable list of local import groups. No API calls.

```tsx
// frontend/src/components/import/ImportMergeGroupPicker.tsx
import { useState, useEffect, useRef, useMemo } from 'react'
import { Search, Layers, Merge } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { EditableGroupState } from '@/types'

interface ImportMergeGroupPickerProps {
  open: boolean
  onClose: () => void
  groups: EditableGroupState[]
  sourceIndex: number
  onSelect: (targetIndex: number) => void
  currentGroupName?: string
}

export function ImportMergeGroupPicker({
  open,
  onClose,
  groups,
  sourceIndex,
  onSelect,
  currentGroupName,
}: ImportMergeGroupPickerProps) {
  const [search, setSearch] = useState('')
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setSearch('')
      setSelectedIndex(null)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  const targets = useMemo(() => {
    const filtered = groups
      .map((g, i) => ({ group: g, index: i }))
      .filter(({ index }) => index !== sourceIndex)
    if (!search.trim()) return filtered
    const q = search.toLowerCase()
    return filtered.filter(({ group }) => group.group_name.toLowerCase().includes(q))
  }, [groups, sourceIndex, search])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md p-0 overflow-hidden gap-0" onClose={onClose}>
        <DialogHeader className="px-5 pt-5 pb-0">
          <DialogTitle className="text-[15px] tracking-wide">
            Merge "{currentGroupName}" into…
          </DialogTitle>
        </DialogHeader>

        <div className="px-5 pt-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/60" />
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search groups..."
              className="w-full h-8 pl-8 pr-3 text-sm bg-secondary border border-border rounded-md text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors"
            />
          </div>
        </div>

        <div className="min-h-[200px] max-h-[320px] overflow-y-auto px-2 pb-2">
          {targets.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-[200px] text-muted-foreground/50">
              <Layers className="h-8 w-8 mb-2 opacity-40" />
              <p className="text-sm">No matching groups</p>
            </div>
          ) : (
            <div className="space-y-px">
              {targets.map(({ group, index }) => {
                const isSelected = selectedIndex === index
                const fileCount = group.files.filter((f) => !f.excluded).length
                return (
                  <button
                    key={group.id}
                    onClick={() => setSelectedIndex(index)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-all duration-100 ${
                      isSelected ? 'bg-primary/15 ring-1 ring-primary/40' : 'hover:bg-muted/50'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <p className={`text-[13px] font-medium leading-tight truncate ${isSelected ? 'text-primary' : 'text-foreground'}`}>
                        {group.group_name}
                      </p>
                    </div>
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/50 bg-muted/40 px-1.5 py-0.5 rounded">
                      {fileCount}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border/30 bg-muted/10">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded-md border border-border/50 text-muted-foreground hover:text-foreground hover:border-border transition-colors">
            Cancel
          </button>
          <button
            onClick={() => selectedIndex !== null && onSelect(selectedIndex)}
            disabled={selectedIndex === null}
            className="px-4 py-1.5 text-sm rounded-md font-medium bg-primary/90 text-primary-foreground hover:bg-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            <Merge className="h-3.5 w-3.5" />
            Merge
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

**Step 2: Replace inline merge list in ImportGroupNav**

In `ImportGroupNav.tsx`:
- Add state: `const [mergeSourceIndex, setMergeSourceIndex] = useState<number | null>(null)`
- Replace the inline `DropdownMenuLabel` + mapped `DropdownMenuItem`s (lines 133-147) with a single item:
  ```tsx
  {groups.length > 1 && (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem onClick={() => setMergeSourceIndex(i)}>
        <Merge className="h-4 w-4 mr-2" />
        Merge into…
      </DropdownMenuItem>
    </>
  )}
  ```
- Render `ImportMergeGroupPicker` after `GroupSidebarShell`:
  ```tsx
  <ImportMergeGroupPicker
    open={mergeSourceIndex !== null}
    onClose={() => setMergeSourceIndex(null)}
    groups={groups}
    sourceIndex={mergeSourceIndex ?? 0}
    onSelect={(targetIndex) => {
      if (mergeSourceIndex !== null) {
        onMergeGroups(mergeSourceIndex, targetIndex)
        setMergeSourceIndex(null)
      }
    }}
    currentGroupName={mergeSourceIndex !== null ? groups[mergeSourceIndex]?.group_name : ''}
  />
  ```
- Remove the now-unused `DropdownMenuLabel` import.

**Step 3: Commit**

```bash
git add frontend/src/components/import/ImportMergeGroupPicker.tsx frontend/src/components/import/ImportGroupNav.tsx
git commit -m "feat: replace inline merge list with searchable ImportMergeGroupPicker"
```

---

### Task 3: Skip group button on detail page

**Problem:** "Skip Group" is only accessible via the `...` dropdown in the sidebar nav, not discoverable.

**Files:**
- Modify: `frontend/src/components/import/ImportGroupContent.tsx`

**Step 1: Add Skip button to pending-group footer**

In `ImportGroupContent.tsx`, find the pending-group footer section (lines 476-492). Add a "Skip Group" button to the left side of the footer (next to the file count):

Replace lines 476-492:
```tsx
{activeGroup.status === 'pending' && (
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted-foreground">
        {activeGroup.files.filter((f) => !f.excluded).length} of{' '}
        {activeGroup.files.length} files
      </span>
      <button
        onClick={() => updateGroup(activeTab, { skip: true })}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors"
      >
        <SkipForward className="h-3 w-3" />
        Skip
      </button>
    </div>
    <button
      onClick={() => handleConfirmGroup(activeTab)}
      disabled={!canImportActive}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    >
      Import Group
      <span className="opacity-60 text-xs">
        ({activeGroup.files.filter((f) => !f.excluded).length})
      </span>
    </button>
  </div>
)}
```

Note: `SkipForward` is already imported at line 3.

**Step 2: Commit**

```bash
git add frontend/src/components/import/ImportGroupContent.tsx
git commit -m "feat: add skip group button to import group detail footer"
```

---

### Task 4: `...` icon as part of the row

**Problem:** The `MoreHorizontal` trigger is visually separate from the nav row — doesn't share background/border on hover or selection.

**Files:**
- Modify: `frontend/src/components/import/ImportGroupNav.tsx` (lines 100-151)
- Modify: `frontend/src/components/EditGroupDialog.tsx` (lines 416-476)

**Step 1: Fix ImportGroupNav active group rows**

Move the visual styling (border-l-2, background, text color) from the inner `<button>` to the parent `<div>`. The inner `<button>` becomes a transparent flex-fill element. The dropdown trigger inherits the row's visual context.

Replace lines 100-151 with:
```tsx
<div
  className={`flex items-center group/nav transition-colors border-l-2 ${
    activeTab === i
      ? 'border-primary bg-primary/10 text-primary'
      : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
  } ${g.skip ? 'opacity-40' : ''}`}
>
  <button
    onClick={() => onSelectTab(i)}
    className="flex-1 flex items-center gap-2 px-3 py-2 text-left min-w-0"
  >
    <span className="shrink-0 w-3 flex justify-center">
      {!g.skip && (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50 inline-block" />
      )}
      {g.skip && <SkipForward className="h-3 w-3" />}
    </span>
    <span className={`flex-1 text-[12px] truncate ${g.skip ? 'line-through' : ''}`}>
      {g.group_name}
    </span>
    <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
      {g.files.filter((f) => !f.excluded).length}
    </span>
  </button>
  <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <button className="opacity-0 group-hover/nav:opacity-100 focus:opacity-100 p-1.5 mr-1 text-muted-foreground/40 hover:text-muted-foreground transition-all shrink-0 rounded hover:bg-black/5 dark:hover:bg-white/5">
        <MoreHorizontal className="h-3.5 w-3.5" />
      </button>
    </DropdownMenuTrigger>
    {/* ... dropdown content unchanged ... */}
  </DropdownMenu>
</div>
```

**Step 2: Fix EditGroupDialog sidebar rows**

Apply the same pattern to `EditGroupDialog.tsx` lines 416-476. Move `border-l-2`, `bg-primary/*`, `text-primary`, and hover classes from the inner `<button>` (line 419-425) to the parent `<div>` (line 416). The inner `<button>` becomes a transparent flex-fill. The dropdown trigger button (line 446) gets the same subtle hover treatment.

```tsx
<div className={`flex items-center transition-colors border-l-2 ${
  selectedGroupIds.has(g.id)
    ? 'border-primary/60 bg-primary/15 text-primary'
    : activeTab === i
      ? 'border-primary bg-primary/10 text-primary'
      : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
}`}>
  <button
    onClick={(e) => handleGroupClick(i, g.id, e)}
    className="flex-1 flex items-center gap-2 pl-3 pr-1 py-2 text-left min-w-0"
  >
    {/* ... existing content: name, count, save status ... */}
  </button>
  {isMassEdit && (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="opacity-0 group-hover/navrow:opacity-100 focus:opacity-100 h-7 w-6 mr-1 flex items-center justify-center rounded text-muted-foreground/50 hover:text-foreground hover:bg-black/5 dark:hover:bg-white/5 transition-all shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </DropdownMenuTrigger>
      {/* ... dropdown content unchanged ... */}
    </DropdownMenu>
  )}
</div>
```

Note: The `group/navrow` class needs to move to the outer div (from line 392) so the dropdown trigger hover-reveal still works. Since the outer div is now the visual row, add `group/navrow` there and remove it from the inner wrapper div.

**Step 3: Commit**

```bash
git add frontend/src/components/import/ImportGroupNav.tsx frontend/src/components/EditGroupDialog.tsx
git commit -m "feat: make ... dropdown trigger part of sidebar row visuals"
```

---

### Task 5: Custom scrollbar for group sidebar

**Problem:** No Firefox scrollbar support. Webkit styles exist globally but the sidebar scrollbar looks like the OS default on Firefox.

**Files:**
- Modify: `frontend/src/index.css` (lines 118-136)

**Step 1: Add Firefox scrollbar properties**

After the existing webkit scrollbar rules (line 135), add standard CSS properties:

```css
/* ── Scrollbars ──────────────────────────────────────────── */

/* Standard (Firefox, future browsers) */
* {
  scrollbar-width: thin;
  scrollbar-color: hsl(var(--border)) transparent;
}

/* Webkit (Chrome, Safari, Edge) */
::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: hsl(var(--border));
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.35);
}
```

Note: The `scrollbar-width: thin` and `scrollbar-color` are applied to `*` so they affect all scrollable elements including the sidebar. The webkit rules override for Chrome/Safari/Edge.

**Step 2: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: add Firefox scrollbar support with thin scrollbars"
```

---

## Task Summary

| # | Task | Files | Approx effort |
|---|------|-------|---------------|
| 1 | Click-to-select + magnify icon | `FileCardThumbnail.tsx` | Small |
| 2 | ImportMergeGroupPicker | New file + `ImportGroupNav.tsx` | Medium |
| 3 | Skip group button in footer | `ImportGroupContent.tsx` | Small |
| 4 | `...` icon as part of row | `ImportGroupNav.tsx`, `EditGroupDialog.tsx` | Medium |
| 5 | Firefox scrollbar support | `index.css` | Small |

Tasks 1, 3, 5 are independent. Task 4 modifies `ImportGroupNav.tsx` which is also touched by Task 2 — do Task 2 first, then Task 4.

**Recommended order:** 5 → 1 → 3 → 2 → 4
