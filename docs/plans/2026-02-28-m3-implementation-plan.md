# M3: Shared Primitives + Import DnD — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract shared UI primitives from duplicate card/toolbar components, extract DnD wrappers from EditGroupDialog, and add full drag-and-drop to the import flow.

**Architecture:** Extract reusable DnD wrapper components and card/toolbar primitives into `frontend/src/components/import/shared/`. Each DnD consumer (EditGroupDialog, ImportGroupContent) keeps its own `DndContext` with context-specific handlers. A new `moveFilesToGroup` state operation enables client-side card→group moves in the import flow.

**Tech Stack:** React 18, @dnd-kit/core, @tanstack/react-virtual, TypeScript, Vitest, Tailwind CSS

**Styling philosophy:** When extracting shared primitives, take a thoughtful approach to styling divergences. Some differences between FileCard and ImportFileCard are **deliberate** (e.g. ImportFileCard is a simpler preview card per the import design philosophy — see `design/web-import.md`). Others are **accidental** (copy-paste drift). When unifying, normalize accidental differences (e.g. inconsistent opacity values, missing hover states) but preserve intentional ones (e.g. FileCard has `small` thumbnail for out-of-scope, ImportFileCard doesn't need it). When in doubt, favor the more polished version.

---

## Phase 1: DnD Extraction (pure refactor)

### Task 1: Extract shared DnD types and wrapper components

**Files:**
- Create: `frontend/src/components/import/shared/dnd/types.ts`
- Create: `frontend/src/components/import/shared/dnd/DraggableFileCardWrapper.tsx`
- Create: `frontend/src/components/import/shared/dnd/DroppableGroupRow.tsx`
- Create: `frontend/src/components/import/shared/dnd/DroppableSubgroupSection.tsx`
- Create: `frontend/src/components/import/shared/dnd/DraggableGroupRow.tsx`
- Create: `frontend/src/components/import/shared/dnd/DragOverlayContent.tsx`
- Create: `frontend/src/components/import/shared/dnd/index.ts`

**Step 1: Create `shared/dnd/types.ts`**

Extract from `EditGroupDialog.tsx` lines 113-132:

```ts
export interface DragData {
  type: 'card' | 'group'
  id: string
  groupId: string
}

export interface DropData {
  type: 'group' | 'subgroup'
  groupId?: string
  subgroup?: string | null
}

export interface ActiveDragState {
  type: 'card' | 'group'
  id: string
  groupId: string
  selectedCount: number
  previewUrl?: string
  label?: string
}
```

**Step 2: Create the 4 wrapper components**

Each is a direct copy from `EditGroupDialog.tsx` lines 136-240, using the shared types. Signatures:

- `DraggableFileCardWrapper({ file, groupId, isDndEnabled, children })` — uses `useDraggable`, ID: `card-${groupId}-${file.relative_path}`, disabled when `!isDndEnabled || file.excluded || file.outOfScope`
- `DroppableGroupRow({ groupId, activeDrag, children })` — uses `useDroppable`, ID: `group-drop-${groupId}`, disabled when `!activeDrag || activeDrag.groupId === groupId`
- `DraggableGroupRow({ groupId, isDndEnabled, children })` — uses `useDraggable`, ID: `group-${groupId}`
- `DroppableSubgroupSection({ subVariant, activeDrag, children })` — uses `useDroppable`, ID: `subgroup-${subVariant ?? '__main__'}`, disabled when `!activeDrag || activeDrag.type !== 'card'`

Import `useDraggable`/`useDroppable` from `@dnd-kit/core`. Import types from `./types`. Import `EditableFileState` from `@/types`.

**Step 3: Create `DragOverlayContent.tsx`**

Extract the DragOverlay children from `EditGroupDialog.tsx` lines 1708-1733:

```tsx
import { GripVertical } from 'lucide-react'
import type { ActiveDragState } from './types'

export function DragOverlayContent({ activeDrag }: { activeDrag: ActiveDragState | null }) {
  if (!activeDrag) return null

  if (activeDrag.type === 'card') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-primary/50 bg-card shadow-lg px-3 py-2 pointer-events-none max-w-[200px]">
        {activeDrag.previewUrl && (
          <img src={activeDrag.previewUrl} alt="" className="w-10 h-10 object-cover rounded shrink-0" />
        )}
        <span className="text-xs text-foreground truncate">{activeDrag.label ?? 'Image'}</span>
        {activeDrag.selectedCount > 1 && (
          <span className="ml-auto shrink-0 w-5 h-5 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
            {activeDrag.selectedCount}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-primary/50 bg-card shadow-lg px-3 py-2 pointer-events-none max-w-[180px]">
      <GripVertical className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
      <span className="text-xs text-foreground truncate">{activeDrag.label ?? 'Group'}</span>
    </div>
  )
}
```

**Step 4: Create barrel `index.ts`**

Re-export all components and types from `./types`, `./DraggableFileCardWrapper`, etc.

**Step 5: Run build to verify no type errors**

Run: `cd frontend && npm run build`
Expected: PASS — new files compile but aren't used yet

**Step 6: Commit**

```bash
git add frontend/src/components/import/shared/dnd/
git commit -m "Extract shared DnD wrapper components from EditGroupDialog"
```

---

### Task 2: Update EditGroupDialog to use shared DnD wrappers

**Files:**
- Modify: `frontend/src/components/EditGroupDialog.tsx`

**Step 1: Replace inline DnD code with imports**

At the top of EditGroupDialog.tsx, add:
```ts
import {
  DraggableFileCardWrapper,
  DroppableGroupRow,
  DraggableGroupRow,
  DroppableSubgroupSection,
  DragOverlayContent,
  type DragData,
  type DropData,
  type ActiveDragState,
} from './import/shared/dnd'
```

Remove:
- Lines 111-240 (the inline type definitions and 4 wrapper component definitions)
- The `<DragOverlay>` JSX block at lines 1707-1735, replace with:
```tsx
<DragOverlay dropAnimation={null}>
  <DragOverlayContent activeDrag={activeDrag} />
</DragOverlay>
```

**Step 2: Run tests and build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: All 202 tests pass, build succeeds. This is a pure extraction — behavior unchanged.

**Step 3: Commit**

```bash
git add frontend/src/components/EditGroupDialog.tsx
git commit -m "Use shared DnD wrappers in EditGroupDialog"
```

---

## Phase 2: Shared Card Primitives

### Task 3: Extract shared card primitives

**Files:**
- Create: `frontend/src/components/import/shared/FileCardThumbnail.tsx`
- Create: `frontend/src/components/import/shared/FileCardExcludedState.tsx`
- Create: `frontend/src/components/import/shared/FileCardLightbox.tsx`
- Create: `frontend/src/components/import/shared/TypeToggleInline.tsx`
- Create: `frontend/src/components/import/shared/SubgroupRow.tsx`

**Step 1: Create `FileCardThumbnail.tsx`**

Extract the `renderThumb` function from both cards. Unify the `small` option (FileCard-only) as an optional prop:

```tsx
import type { EditableFileState } from '@/types'

interface FileCardThumbnailProps {
  file: EditableFileState
  previewUrl: string
  useVideoThumb: boolean
  selected: boolean
  dimmed?: boolean
  small?: boolean
  /** Hide checkbox (e.g. for skipped duplicates) */
  hideCheckbox?: boolean
  onOpenLightbox: () => void
}

export function FileCardThumbnail({
  file,
  previewUrl,
  useVideoThumb,
  selected,
  dimmed,
  small,
  hideCheckbox,
  onOpenLightbox,
}: FileCardThumbnailProps) {
  const cls = small ? 'w-20' : 'w-[140px]'
  const filter = dimmed ? 'grayscale(0.6)' : undefined

  return (
    <button
      type="button"
      className={`${cls} shrink-0 relative overflow-hidden rounded-l-lg bg-secondary cursor-zoom-in min-h-[80px]`}
      style={{ filter }}
      onClick={() => { if (previewUrl) onOpenLightbox() }}
      tabIndex={-1}
    >
      {useVideoThumb ? (
        <video
          src={previewUrl}
          muted
          preload="metadata"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
        />
      ) : (
        <img
          src={previewUrl}
          alt={file.filename}
          loading="lazy"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none transition-transform duration-300 group-hover/card:scale-[1.04]"
          onError={(e) => {
            const el = e.target as HTMLImageElement
            el.style.display = 'none'
            el.parentElement!.classList.add('flex', 'items-center', 'justify-center')
            const placeholder = document.createElement('span')
            placeholder.className = 'text-[10px] text-muted-foreground/40 font-medium text-center px-1'
            placeholder.textContent = 'No preview'
            el.parentElement!.appendChild(placeholder)
          }}
        />
      )}
      {!dimmed && !hideCheckbox && (
        <div
          className={`absolute top-1.5 left-1.5 w-4 h-4 rounded-[3px] flex items-center justify-center text-[9px] transition-all backdrop-blur-sm ${
            selected
              ? 'bg-primary/90 border-primary text-primary-foreground font-bold'
              : 'bg-black/35 border-white/20 text-transparent'
          } border-[1.5px]`}
        >
          ✓
        </div>
      )}
    </button>
  )
}
```

**Step 2: Create `FileCardExcludedState.tsx`**

```tsx
import { Undo2 } from 'lucide-react'
import { FileCardThumbnail } from './FileCardThumbnail'
import type { EditableFileState } from '@/types'

interface FileCardExcludedStateProps {
  file: EditableFileState
  previewUrl: string
  useVideoThumb: boolean
  disabled?: boolean
  onRestore: () => void
  onOpenLightbox: () => void
}

export function FileCardExcludedState({
  file,
  previewUrl,
  useVideoThumb,
  disabled,
  onRestore,
  onOpenLightbox,
}: FileCardExcludedStateProps) {
  return (
    <div className="flex rounded-lg border border-dashed border-border/40 bg-muted/20 opacity-40 overflow-hidden">
      <FileCardThumbnail
        file={file}
        previewUrl={previewUrl}
        useVideoThumb={useVideoThumb}
        selected={false}
        dimmed
        onOpenLightbox={onOpenLightbox}
      />
      <div className="flex-1 min-w-0 py-2 px-2.5 flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <span
            className="font-display text-[12px] text-muted-foreground/40 line-through truncate block"
            title={file.relative_path}
          >
            {file.name || file.filename}
          </span>
          <span className="font-mono text-[9px] text-muted-foreground/25 truncate block">
            {file.filename}
          </span>
        </div>
        {!disabled && (
          <button
            onClick={onRestore}
            className="text-xs text-muted-foreground hover:text-primary transition-colors shrink-0 flex items-center gap-1"
          >
            <Undo2 className="h-3 w-3" />
            Restore
          </button>
        )}
      </div>
    </div>
  )
}
```

**Step 3: Create `FileCardLightbox.tsx`**

```tsx
import { Dialog, DialogContent } from '@/components/ui/dialog'

interface FileCardLightboxProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  src: string
  alt: string
  isVideo: boolean
}

export function FileCardLightbox({ open, onOpenChange, src, alt, isVideo }: FileCardLightboxProps) {
  if (!open) return null
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-none max-h-none w-[95vw] h-[95vh] bg-black/95 border-0 p-4 flex items-center justify-center [&>button]:text-white [&>button]:hover:bg-white/20 cursor-pointer"
        onClick={() => onOpenChange(false)}
      >
        {isVideo ? (
          <video
            src={src}
            controls
            autoPlay
            loop
            className="max-w-full max-h-full object-contain rounded cursor-default"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <img
            src={src}
            alt={alt}
            className="max-w-full max-h-full object-contain rounded cursor-default"
            onClick={(e) => e.stopPropagation()}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
```

**Step 4: Create `TypeToggleInline.tsx`**

Extract the Map/Scene toggle used on card TYPE rows (identical in both cards):

```tsx
import type { EditableFileState } from '@/types'

interface TypeToggleInlineProps {
  imageType: EditableFileState['image_type']
  disabled?: boolean
  onUpdate: (imageType: 'battlemap' | 'scene') => void
}

export function TypeToggleInline({ imageType, disabled, onUpdate }: TypeToggleInlineProps) {
  if (disabled) {
    return (
      <span className="text-[10px] text-muted-foreground/60 capitalize">
        {imageType === 'scene' ? 'Scene' : 'Map'}
      </span>
    )
  }
  return (
    <div className="inline-flex rounded-md overflow-hidden border border-border">
      <button
        onClick={() => onUpdate('battlemap')}
        className={`px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
          imageType !== 'scene'
            ? 'bg-primary/20 text-primary'
            : 'text-muted-foreground/50 hover:text-muted-foreground'
        }`}
      >
        Map
      </button>
      <button
        onClick={() => onUpdate('scene')}
        className={`px-1.5 py-0.5 text-[10px] font-medium border-l border-border transition-colors ${
          imageType === 'scene'
            ? 'bg-primary/20 text-primary'
            : 'text-muted-foreground/50 hover:text-muted-foreground'
        }`}
      >
        Scene
      </button>
    </div>
  )
}
```

**Step 5: Create `SubgroupRow.tsx`**

Extract the SUB prop-row (identical in both cards):

```tsx
import { useState } from 'react'
import { X } from 'lucide-react'
import { SubgroupDropdown } from '@/components/SubgroupDropdown'

interface SubgroupRowProps {
  subgroup: string | null
  existingSubgroups: string[]
  disabled?: boolean
  onUpdate: (subgroup: string | null) => void
}

export function SubgroupRow({ subgroup, existingSubgroups, disabled, onUpdate }: SubgroupRowProps) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div className="flex items-center gap-1.5 min-h-5">
      <span className="w-8 shrink-0 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 text-right leading-none">
        Sub
      </span>
      <div className="flex-1 min-w-0 flex items-center gap-1 relative">
        {subgroup ? (
          <button
            data-no-select=""
            className={`flex-1 min-w-0 h-5 px-1.5 text-[10px] bg-secondary border border-border text-foreground/80 capitalize text-left truncate flex items-center gap-1 hover:border-primary/40 transition-colors ${isOpen ? 'rounded-t border-b-0' : 'rounded'}`}
            onClick={() => !disabled && setIsOpen(true)}
          >
            <span className="truncate">{subgroup}</span>
            {!disabled && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onUpdate(null)
                }}
                className="ml-auto shrink-0 text-muted-foreground/30 hover:text-foreground opacity-0 group-hover/card:opacity-100 transition-opacity"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            )}
          </button>
        ) : (
          <button
            data-no-select=""
            className={`flex-1 min-w-0 h-5 px-1.5 text-[10px] bg-secondary border border-border text-muted-foreground/30 italic text-left truncate hover:border-primary/40 transition-colors ${isOpen ? 'rounded-t border-b-0' : 'rounded'}`}
            onClick={() => !disabled && setIsOpen(true)}
            disabled={disabled}
          >
            —
          </button>
        )}
        <SubgroupDropdown
          isOpen={isOpen}
          existingSubgroups={existingSubgroups}
          initialValue={subgroup ?? ''}
          variant="attached"
          onCommit={(value) => {
            onUpdate(value || null)
            setIsOpen(false)
          }}
          onCancel={() => setIsOpen(false)}
        />
      </div>
    </div>
  )
}
```

**Step 6: Run build**

Run: `cd frontend && npm run build`
Expected: PASS — new files compile, not imported yet

**Step 7: Commit**

```bash
git add frontend/src/components/import/shared/FileCardThumbnail.tsx frontend/src/components/import/shared/FileCardExcludedState.tsx frontend/src/components/import/shared/FileCardLightbox.tsx frontend/src/components/import/shared/TypeToggleInline.tsx frontend/src/components/import/shared/SubgroupRow.tsx
git commit -m "Extract shared card primitives (thumbnail, excluded, lightbox, type toggle, subgroup)"
```

---

### Task 4: Update FileCard and ImportFileCard to use shared primitives

**Files:**
- Modify: `frontend/src/components/import/FileCard.tsx`
- Modify: `frontend/src/components/import/ImportFileCard.tsx`

**Step 1: Update FileCard.tsx**

Replace inline implementations with shared components:
- Replace `renderThumb()` calls with `<FileCardThumbnail>` component
- Replace excluded state block with `<FileCardExcludedState>`
- Replace lightbox Dialog with `<FileCardLightbox>`
- Replace SUB prop-row with `<SubgroupRow>` (remove local `isSubgroupOpen` state)
- Replace TYPE prop-row toggle with `<TypeToggleInline>`

Keep unique to FileCard: out-of-scope state, name editing, grid controls, tags section, duplicate badge.

The `lightboxOpen` state and computed `previewUrl`/`isVideo`/`useVideoThumb` remain in FileCard since they're used by multiple sub-components.

**Step 2: Update ImportFileCard.tsx**

Same replacements:
- `renderThumb()` → `<FileCardThumbnail>` (with `hideCheckbox` for skipped state)
- excluded block → `<FileCardExcludedState>`
- lightbox Dialog → `<FileCardLightbox>`
- SUB row → `<SubgroupRow>` (remove local `isSubgroupOpen` state)
- TYPE row toggle → `<TypeToggleInline>`

Keep unique to ImportFileCard: skipped-duplicate state rendering, duplicate badge on TYPE row.

**Step 3: Run tests and build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: All tests pass, build succeeds. Behavior unchanged — just composition.

**Step 4: Commit**

```bash
git add frontend/src/components/import/FileCard.tsx frontend/src/components/import/ImportFileCard.tsx
git commit -m "Compose FileCard and ImportFileCard from shared primitives"
```

---

## Phase 3: Shared Toolbar Primitives

### Task 5: Extract shared TypeToggle and update toolbars

**Files:**
- Create: `frontend/src/components/import/shared/TypeToggle.tsx`
- Modify: `frontend/src/components/import/FileToolbar.tsx`
- Modify: `frontend/src/components/import/ImportFileToolbar.tsx`

**Step 1: Create `shared/TypeToggle.tsx`**

Extract the `TypeToggle` component that is duplicated verbatim in both FileToolbar (lines 410-439) and ImportFileToolbar (lines 261-290):

```tsx
import type { ImageTypeFilter } from '../fileFilter'

interface TypeToggleProps {
  value: ImageTypeFilter
  onChange: (v: ImageTypeFilter) => void
}

const opts: { label: string; val: ImageTypeFilter }[] = [
  { label: 'All', val: 'all' },
  { label: 'Maps', val: 'battlemap' },
  { label: 'Scenes', val: 'scene' },
]

export function TypeToggle({ value, onChange }: TypeToggleProps) {
  return (
    <div className="inline-flex rounded border border-border overflow-hidden shrink-0">
      {opts.map((opt) => (
        <button
          key={opt.val}
          onClick={() => onChange(opt.val)}
          className={`px-1.5 py-0.5 text-[11px] transition-colors ${
            value === opt.val
              ? 'bg-secondary text-foreground font-medium'
              : 'text-muted-foreground/60 hover:text-muted-foreground hover:bg-secondary/50'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
```

**Step 2: Update FileToolbar.tsx**

- Remove the inline `TypeToggle` function (lines 410-439)
- Add `import { TypeToggle } from './shared/TypeToggle'`

**Step 3: Update ImportFileToolbar.tsx**

- Remove the inline `TypeToggle` function (lines 261-290)
- Add `import { TypeToggle } from './shared/TypeToggle'`

**Step 4: Run tests and build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: All tests pass, build succeeds.

**Step 5: Commit**

```bash
git add frontend/src/components/import/shared/TypeToggle.tsx frontend/src/components/import/FileToolbar.tsx frontend/src/components/import/ImportFileToolbar.tsx
git commit -m "Extract shared TypeToggle from toolbar components"
```

---

## Phase 4: Import DnD (new feature)

### Task 6: Add `moveFilesToGroup` to useImportState (TDD)

**Files:**
- Modify: `frontend/src/hooks/useImportState.ts`
- Create: `frontend/src/hooks/useImportState.moveFiles.test.ts`

**Step 1: Write the failing test**

```ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
// useImportState requires providers — test the underlying useFileEditing instead
import { useFileEditing } from './useFileEditing'
import type { EditableFileState, EditableGroupState } from '@/types'

function makeFile(overrides: Partial<EditableFileState> = {}): EditableFileState {
  return {
    relative_path: 'img.jpg',
    filename: 'img.jpg',
    name: 'img',
    tags: [],
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    subgroup: null,
    image_type: 'battlemap',
    excluded: false,
    ...overrides,
  }
}

function makeGroup(overrides: Partial<EditableGroupState> = {}): EditableGroupState {
  return {
    id: 'g1',
    author: 'Author',
    group_name: 'Group',
    files: [makeFile()],
    skip: false,
    status: 'pending',
    processed: 0,
    failed: 0,
    total: 1,
    ...overrides,
  }
}

// These tests will be updated after moveFilesToGroup is added to useFileEditing
// For now they document the expected behavior
describe('moveFilesToGroup', () => {
  it('moves files from source to target group', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg', name: 'a' })
    const fileB = makeFile({ relative_path: 'b.jpg', name: 'b' })
    const fileC = makeFile({ relative_path: 'c.jpg', name: 'c' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA, fileB] }),
        makeGroup({ id: 'g2', files: [fileC] }),
      ])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg'])
    })

    expect(result.current.groups[0].files).toHaveLength(1)
    expect(result.current.groups[0].files[0].relative_path).toBe('b.jpg')
    expect(result.current.groups[1].files).toHaveLength(2)
    expect(result.current.groups[1].files[1].relative_path).toBe('a.jpg')
  })

  it('removes empty source group after move', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA] }),
        makeGroup({ id: 'g2', files: [fileB] }),
      ])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg'])
    })

    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].id).toBe('g2')
  })

  it('clears selection for source group after move', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA, fileB] }),
        makeGroup({ id: 'g2', files: [] }),
      ])
    })

    act(() => {
      result.current.toggleFileSelection('g1', 'a.jpg')
      result.current.toggleFileSelection('g1', 'b.jpg')
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg'])
    })

    expect(result.current.selections['g1']?.size ?? 0).toBe(0)
  })
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/useImportState.moveFiles.test.ts`
Expected: FAIL — `moveFilesToGroup` is not defined on the hook return

**Step 3: Add `moveFilesToGroup` to `useFileEditing`**

In `frontend/src/hooks/useFileEditing.ts`:

1. Add to `UseFileEditingReturn` interface:
```ts
moveFilesToGroup: (sourceGroupId: string, targetGroupId: string, paths: string[]) => void
```

2. Add implementation after `updateFilesInGroup`:
```ts
const moveFilesToGroup = (sourceGroupId: string, targetGroupId: string, paths: string[]) => {
  const pathSet = new Set(paths)
  setGroups((prev) => {
    const sourceGroup = prev.find((g) => g.id === sourceGroupId)
    if (!sourceGroup) return prev

    const movedFiles = sourceGroup.files.filter((f) => pathSet.has(f.relative_path))
    if (movedFiles.length === 0) return prev

    const remainingFiles = sourceGroup.files.filter((f) => !pathSet.has(f.relative_path))
    const sourceEmpty = remainingFiles.length === 0

    let newGroups = prev.map((g) => {
      if (g.id === sourceGroupId) {
        return { ...g, files: remainingFiles, total: remainingFiles.length }
      }
      if (g.id === targetGroupId) {
        return { ...g, files: [...g.files, ...movedFiles], total: g.files.length + movedFiles.length }
      }
      return g
    })

    if (sourceEmpty) {
      newGroups = newGroups.filter((g) => g.id !== sourceGroupId)
    }

    const affected = newGroups.filter((g) => g.id === sourceGroupId || g.id === targetGroupId)
    if (affected.length > 0) notifyGroupChange(affected)
    return newGroups
  })

  // Clear selections for source group
  setSelections((prev) => {
    const next = { ...prev }
    delete next[sourceGroupId]
    return next
  })
}
```

3. Add `moveFilesToGroup` to the return object.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/hooks/useImportState.moveFiles.test.ts`
Expected: PASS — all 3 tests pass

**Step 5: Wire `moveFilesToGroup` through `useImportState`**

In `frontend/src/hooks/useImportState.ts`:
1. Add `moveFilesToGroup` to the `editing` group in the return interface
2. Destructure it from `useFileEditing` return
3. Add it to the `editing` sub-object in the return
4. After the move, if the source group was removed and `activeTab` pointed at or beyond it, adjust `activeTab`

The adjustment logic (add after calling `editing.moveFilesToGroup`):
```ts
// In useImportState, wrap the editing.moveFilesToGroup with activeTab adjustment:
const moveFilesToGroup = (sourceGroupId: string, targetGroupId: string, paths: string[]) => {
  const sourceIndex = groups.findIndex((g) => g.id === sourceGroupId)
  const source = groups[sourceIndex]
  if (!source) return

  const remaining = source.files.filter((f) => !new Set(paths).has(f.relative_path))
  editing.moveFilesToGroup(sourceGroupId, targetGroupId, paths)

  // If source group will be empty and removed, adjust activeTab
  if (remaining.length === 0 && sourceIndex <= activeTab) {
    setActiveTab((prev) => Math.max(ALL_TAB, prev - 1))
  }
}
```

**Step 6: Run all tests and build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: All tests pass, build succeeds

**Step 7: Commit**

```bash
git add frontend/src/hooks/useFileEditing.ts frontend/src/hooks/useImportState.ts frontend/src/hooks/useImportState.moveFiles.test.ts
git commit -m "Add moveFilesToGroup for import DnD card-to-group moves"
```

---

### Task 7: Add DnD to ImportGroupNav

**Files:**
- Modify: `frontend/src/components/import/ImportGroupNav.tsx`

**Step 1: Add DnD wrappers to group rows**

Import shared DnD components:
```ts
import { DraggableGroupRow, DroppableGroupRow } from './shared/dnd'
import type { ActiveDragState } from './shared/dnd'
```

Add `activeDrag` prop to `ImportGroupNavProps`:
```ts
activeDrag: ActiveDragState | null
```

Wrap each **active (pending)** group row (line 87 `<div key={g.id}>`) with:
```tsx
<DroppableGroupRow groupId={g.id} activeDrag={activeDrag}>
  <DraggableGroupRow groupId={g.id} isDndEnabled={state === 'preview' && !g.skip}>
    {/* existing group row content */}
  </DraggableGroupRow>
</DroppableGroupRow>
```

Submitted groups get only `DroppableGroupRow` (they can receive cards but can't be dragged):
```tsx
<DroppableGroupRow groupId={g.id} activeDrag={activeDrag}>
  {/* existing submitted group row content */}
</DroppableGroupRow>
```

**Step 2: Run build**

Run: `cd frontend && npm run build`
Expected: PASS (ImportGroupNav now expects `activeDrag` prop — callers not updated yet, but TS should still compile since the prop is not yet passed)

Wait — this will actually cause a TS error because the prop is required. Make it optional for now:
```ts
activeDrag?: ActiveDragState | null
```

**Step 3: Commit**

```bash
git add frontend/src/components/import/ImportGroupNav.tsx
git commit -m "Add DnD wrappers to ImportGroupNav group rows"
```

---

### Task 8: Add DnD to ImportGroupContent (main integration)

**Files:**
- Modify: `frontend/src/components/import/ImportGroupContent.tsx`
- Modify: `frontend/src/components/ImportDialog.tsx`

**Step 1: Add DndContext and handlers to ImportGroupContent**

Add imports:
```ts
import { useCallback, useRef, useMemo, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import type { DragStartEvent, DragEndEvent } from '@dnd-kit/core'
import {
  DraggableFileCardWrapper,
  DroppableSubgroupSection,
  DragOverlayContent,
  type DragData,
  type DropData,
  type ActiveDragState,
} from './shared/dnd'
```

Add DnD state and handlers inside `ImportGroupContent`:
```ts
const [activeDrag, setActiveDrag] = useState<ActiveDragState | null>(null)

const sensors = useSensors(
  useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  useSensor(KeyboardSensor),
)

const handleDragStart = useCallback((event: DragStartEvent) => {
  const data = event.active.data.current as DragData
  if (data.type === 'card') {
    const sel = activeSelection
    const count = sel.has(data.id) ? sel.size : 1
    const file = groups
      .flatMap((g) => g.files)
      .find((f) => f.relative_path === data.id)
    setActiveDrag({
      type: 'card',
      id: data.id,
      groupId: data.groupId,
      selectedCount: count,
      previewUrl: file?.previewUrl,
      label: file?.name || file?.filename,
    })
  } else {
    const group = groups.find((g) => g.id === data.groupId)
    setActiveDrag({
      type: 'group',
      id: data.id,
      groupId: data.groupId,
      selectedCount: 1,
      label: group?.group_name,
    })
  }
}, [activeSelection, groups])

// Refs to avoid stale closures
const moveFilesRef = useRef(s.editing.moveFilesToGroup)
moveFilesRef.current = s.editing.moveFilesToGroup
const updateFilesRef = useRef(s.editing.updateFilesInGroup)
// Note: updateFilesInGroup may need to be added to editing group — check

const handleDragEnd = useCallback((event: DragEndEvent) => {
  const { over } = event
  if (!over || !activeDrag) {
    setActiveDrag(null)
    return
  }

  const dropData = over.data.current as DropData
  const sel = activeSelection
  const paths = sel.has(activeDrag.id) ? [...sel] : [activeDrag.id]

  if (activeDrag.type === 'card' && dropData.type === 'group' && dropData.groupId) {
    moveFilesRef.current(activeDrag.groupId, dropData.groupId, paths)
  } else if (activeDrag.type === 'card' && dropData.type === 'subgroup') {
    // Use updateFile for each path to set subgroup
    for (const path of paths) {
      // Find group index for the path
      const groupIndex = groups.findIndex((g) => g.id === activeDrag.groupId)
      if (groupIndex !== -1) {
        updateFile(groupIndex, path, { subgroup: dropData.subgroup ?? null })
      }
    }
  } else if (activeDrag.type === 'group' && dropData.type === 'group' && dropData.groupId) {
    if (activeDrag.groupId !== dropData.groupId) {
      const sourceIndex = groups.findIndex((g) => g.id === activeDrag.groupId)
      const targetIndex = groups.findIndex((g) => g.id === dropData.groupId)
      if (sourceIndex !== -1 && targetIndex !== -1) {
        s.editing.mergeGroups(sourceIndex, targetIndex)
      }
    }
  }
  setActiveDrag(null)
}, [activeDrag, activeSelection, groups, updateFile, s.editing])
```

**Step 2: Wrap the layout in DndContext**

The main return becomes:
```tsx
<DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
  <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
    {/* ... existing content ... */}
  </div>
  <DragOverlay dropAnimation={null}>
    <DragOverlayContent activeDrag={activeDrag} />
  </DragOverlay>
</DndContext>
```

**Step 3: Wrap ImportFileCards in DraggableFileCardWrapper**

In the `renderCardRow` function and all places `ImportFileCard` is rendered:
```tsx
<DraggableFileCardWrapper
  file={file}
  groupId={activeGroupId}
  isDndEnabled={!disabled && !isAllTab}
>
  <ImportFileCard ... />
</DraggableFileCardWrapper>
```

DnD is disabled on the "All" tab (files from multiple groups) and when the group is not pending.

**Step 4: Wrap subgroup sections in DroppableSubgroupSection**

In the non-virtualized subgroup rendering:
```tsx
<DroppableSubgroupSection subVariant={svGroup.subgroup} activeDrag={activeDrag}>
  {/* SubgroupHeading + renderCardRow */}
</DroppableSubgroupSection>
```

Same for virtualized subgroup headings — wrap the heading + following card rows.

**Step 5: Update ImportDialog to lift DndContext**

The DndContext must wrap both `ImportGroupNav` and `ImportGroupContent` so cards can be dragged onto nav group rows. Move the DndContext into ImportDialog's two-column layout:

```tsx
{(state === 'preview' || state === 'processing') && groups.length > 0 && (
  <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {groups.length > 1 && (
        <ImportGroupNav ... activeDrag={activeDrag} />
      )}
      <ImportGroupContent s={s} activeDrag={activeDrag} />
    </div>
    <DragOverlay dropAnimation={null}>
      <DragOverlayContent activeDrag={activeDrag} />
    </DragOverlay>
  </DndContext>
)}
```

This means the DnD state (activeDrag, sensors, handlers) lives in ImportDialog (or a custom hook called there) rather than in ImportGroupContent. The handlers need access to `s.editing` and `s.files`.

Create a `useImportDnd` hook or inline the handlers in ImportDialog. The hook approach is cleaner:

**Create `frontend/src/hooks/useImportDnd.ts`**:
```ts
import { useState, useCallback, useRef } from 'react'
import { PointerSensor, KeyboardSensor, useSensor, useSensors } from '@dnd-kit/core'
import type { DragStartEvent, DragEndEvent } from '@dnd-kit/core'
import type { DragData, DropData, ActiveDragState } from '@/components/import/shared/dnd'
import type { UseImportStateReturn } from './useImportState'

export function useImportDnd(s: UseImportStateReturn) {
  const [activeDrag, setActiveDrag] = useState<ActiveDragState | null>(null)
  const { groups, activeTab } = s.files
  const { activeSelection } = s.editing

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  )

  // Refs for stable closure
  const moveFilesRef = useRef(s.editing.moveFilesToGroup)
  moveFilesRef.current = s.editing.moveFilesToGroup
  const mergeGroupsRef = useRef(s.editing.mergeGroups)
  mergeGroupsRef.current = s.editing.mergeGroups
  const updateFileRef = useRef(s.editing.updateFile)
  updateFileRef.current = s.editing.updateFile

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const data = event.active.data.current as DragData
    if (data.type === 'card') {
      const sel = activeSelection
      const count = sel.has(data.id) ? sel.size : 1
      const file = groups
        .flatMap((g) => g.files)
        .find((f) => f.relative_path === data.id)
      setActiveDrag({
        type: 'card',
        id: data.id,
        groupId: data.groupId,
        selectedCount: count,
        previewUrl: file?.previewUrl,
        label: file?.name || file?.filename,
      })
    } else {
      const group = groups.find((g) => g.id === data.groupId)
      setActiveDrag({
        type: 'group',
        id: data.id,
        groupId: data.groupId,
        selectedCount: 1,
        label: group?.group_name,
      })
    }
  }, [activeSelection, groups])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { over } = event
    if (!over || !activeDrag) {
      setActiveDrag(null)
      return
    }

    const dropData = over.data.current as DropData
    const sel = activeSelection
    const paths = sel.has(activeDrag.id) ? [...sel] : [activeDrag.id]

    if (activeDrag.type === 'card' && dropData.type === 'group' && dropData.groupId) {
      moveFilesRef.current(activeDrag.groupId, dropData.groupId, paths)
    } else if (activeDrag.type === 'card' && dropData.type === 'subgroup') {
      const groupIndex = groups.findIndex((g) => g.id === activeDrag.groupId)
      if (groupIndex !== -1) {
        for (const path of paths) {
          updateFileRef.current(groupIndex, path, { subgroup: dropData.subgroup ?? null })
        }
      }
    } else if (activeDrag.type === 'group' && dropData.type === 'group' && dropData.groupId) {
      if (activeDrag.groupId !== dropData.groupId) {
        const sourceIndex = groups.findIndex((g) => g.id === activeDrag.groupId)
        const targetIndex = groups.findIndex((g) => g.id === dropData.groupId)
        if (sourceIndex !== -1 && targetIndex !== -1) {
          mergeGroupsRef.current(sourceIndex, targetIndex)
        }
      }
    }
    setActiveDrag(null)
  }, [activeDrag, activeSelection, groups])

  return { activeDrag, sensors, handleDragStart, handleDragEnd }
}
```

**Step 6: Run tests and build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: All tests pass, build succeeds

**Step 7: Commit**

```bash
git add frontend/src/hooks/useImportDnd.ts frontend/src/components/ImportDialog.tsx frontend/src/components/import/ImportGroupContent.tsx frontend/src/components/import/ImportGroupNav.tsx
git commit -m "Add drag-and-drop to import flow (card→group, card→subgroup, group→group)"
```

---

### Task 9: Final verification and cleanup

**Step 1: Run full test suite**

Run: `cd frontend && npx vitest run`
Expected: All tests pass (202+ tests)

**Step 2: Run build**

Run: `cd frontend && npm run build`
Expected: No type errors, clean build

**Step 3: Run formatting**

Run: `cd frontend && npx prettier --write .`
Then: `cd frontend && npx prettier --check .`
Expected: All clean

**Step 4: Verify line count reduction**

Run: `wc -l frontend/src/components/import/FileCard.tsx frontend/src/components/import/ImportFileCard.tsx frontend/src/components/import/FileToolbar.tsx frontend/src/components/import/ImportFileToolbar.tsx frontend/src/components/EditGroupDialog.tsx`

Expected: Significant reduction from original totals (1573 for cards+toolbars, ~1600 for EditGroupDialog).

**Step 5: Final commit**

```bash
git add -A
git commit -m "M3: Shared primitives + import drag-and-drop"
```

---

## Summary of deliverables

| Task | Description | Files | Risk |
|------|-------------|-------|------|
| 1 | Extract DnD wrappers | 7 new | Low — pure copy |
| 2 | Update EditGroupDialog | 1 modified | Low — swap imports |
| 3 | Extract card primitives | 5 new | Low — pure copy |
| 4 | Update FileCard + ImportFileCard | 2 modified | Medium — recomposition |
| 5 | Extract TypeToggle, update toolbars | 3 modified/new | Low — pure copy |
| 6 | Add moveFilesToGroup (TDD) | 2 modified, 1 new | Low — new fn with tests |
| 7 | DnD wrappers in ImportGroupNav | 1 modified | Low — add wrappers |
| 8 | DnD context in ImportDialog | 4 modified/new | Medium — new feature |
| 9 | Final verification | 0 | None |
