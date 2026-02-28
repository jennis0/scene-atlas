# M3: Shared Primitives + Import Drag-and-Drop

**Date:** 2026-02-28
**Status:** Approved

## Goal

1. Extract shared UI primitives from duplicate FileCard/ImportFileCard and FileToolbar/ImportFileToolbar components
2. Extract DnD wrapper components from EditGroupDialog into reusable shared modules
3. Add full drag-and-drop support to the import flow (card→group, card→subgroup, group→group merge)

## Background

- FileCard (472 lines) and ImportFileCard (372 lines) share ~51% of their code
- FileToolbar (439 lines) and ImportFileToolbar (290 lines) share ~64% of their code
- EditGroupDialog has 4 inline DnD wrapper components that should be reusable
- The import flow currently has no drag-and-drop support

## Architecture

### Shared DnD Components (`shared/dnd/`)

Extract from EditGroupDialog:

| Component | Purpose |
|-----------|---------|
| `types.ts` | `DragData`, `DropData`, `ActiveDragState` interfaces |
| `DraggableFileCardWrapper` | Wraps a card to make it draggable via `useDraggable()` |
| `DroppableGroupRow` | Makes a group row a drop target via `useDroppable()` |
| `DroppableSubgroupSection` | Makes a subgroup section a card drop target |
| `DraggableGroupRow` | Makes a group row draggable for merge operations |
| `DragOverlayContent` | Floating drag preview (thumbnail+count for cards, icon+name for groups) |

Each consumer (EditGroupDialog, ImportGroupContent) provides its own `DndContext` with context-specific handlers:
- **EditGroupDialog:** Handlers call server APIs (`groupApi.moveImages`, `groupApi.merge`)
- **ImportGroupContent:** Handlers call client-side state mutations (`moveFilesToGroup`, `updateFilesInGroup`, `mergeGroups`)

### New Import State Operation

`moveFilesToGroup(sourceGroupId, targetGroupId, paths)` in useImportState:
- Removes files from source group, appends to target
- Updates totals on both groups
- Clears source selections
- Removes empty source groups, adjusts activeTab

### Import DnD Integration

- `ImportGroupContent` gets a `DndContext` with PointerSensor (8px) + KeyboardSensor
- Each `ImportFileCard` wrapped in `DraggableFileCardWrapper` (disabled when status !== 'pending')
- Subgroup sections wrapped in `DroppableSubgroupSection`
- `ImportGroupNav` group rows wrapped in `DraggableGroupRow` + `DroppableGroupRow`

Drop operations:
1. **Card → Group nav row:** `moveFilesToGroup(source, target, selectedPaths)`
2. **Card → Subgroup section:** `updateFilesInGroup(groupId, paths, { subgroup })`
3. **Group → Group nav row:** `mergeGroups(sourceIndex, targetIndex)`

### Shared Card Primitives (`shared/`)

| Component | Extracted from | ~Lines |
|-----------|---------------|--------|
| `FileCardThumbnail` | Video/image preview + selection checkbox | ~50 |
| `FileCardExcludedState` | Excluded file rendering + Undo button | ~30 |
| `FileCardLightbox` | Full-size image/video dialog | ~30 |
| `TypeToggleInline` | Map/Scene toggle on cards | ~25 |
| `SubgroupRow` | Subgroup dropdown row on cards | ~40 |

### Shared Toolbar Primitives (`shared/`)

| Component | Extracted from | ~Lines |
|-----------|---------------|--------|
| `TypeToggle` | Map/Scene bulk toggle | ~30 |
| `FileToolbarCore` | Checkbox, count, search, filter chips layout | ~150 |

### Resulting Component Sizes

| Component | Before | After |
|-----------|--------|-------|
| FileCard.tsx | 472 | ~180 |
| ImportFileCard.tsx | 372 | ~140 |
| FileToolbar.tsx | 439 | ~200 |
| ImportFileToolbar.tsx | 290 | ~60 |
| EditGroupDialog.tsx | ~1600 | ~1400 (DnD wrappers extracted) |

## Files

### New files (13)
- `frontend/src/components/import/shared/dnd/types.ts`
- `frontend/src/components/import/shared/dnd/DraggableFileCardWrapper.tsx`
- `frontend/src/components/import/shared/dnd/DroppableGroupRow.tsx`
- `frontend/src/components/import/shared/dnd/DroppableSubgroupSection.tsx`
- `frontend/src/components/import/shared/dnd/DraggableGroupRow.tsx`
- `frontend/src/components/import/shared/dnd/DragOverlayContent.tsx`
- `frontend/src/components/import/shared/FileCardThumbnail.tsx`
- `frontend/src/components/import/shared/FileCardExcludedState.tsx`
- `frontend/src/components/import/shared/FileCardLightbox.tsx`
- `frontend/src/components/import/shared/TypeToggleInline.tsx`
- `frontend/src/components/import/shared/SubgroupRow.tsx`
- `frontend/src/components/import/shared/TypeToggle.tsx`
- `frontend/src/components/import/shared/FileToolbarCore.tsx`

### Modified files (8)
- `frontend/src/components/EditGroupDialog.tsx` — import DnD wrappers from shared
- `frontend/src/components/import/ImportGroupContent.tsx` — add DndContext, wrap cards
- `frontend/src/components/import/ImportGroupNav.tsx` — wrap group rows in DnD wrappers
- `frontend/src/components/import/FileCard.tsx` — compose from shared primitives
- `frontend/src/components/import/ImportFileCard.tsx` — compose from shared primitives
- `frontend/src/components/import/FileToolbar.tsx` — compose from shared FileToolbarCore
- `frontend/src/components/import/ImportFileToolbar.tsx` — compose from shared FileToolbarCore
- `frontend/src/hooks/useImportState.ts` — add moveFilesToGroup

## Risk Areas

- `data-no-select` attributes must be preserved on extracted sub-components
- Tailwind class divergence between card variants needs careful diffing
- DraggableFileCardWrapper in EditGroupDialog wraps FileCard externally — extraction is safe
- Virtualization in ImportGroupContent: DnD wrappers must work with `@tanstack/react-virtual`

## Verification

```bash
cd frontend
npx vitest run           # all tests pass
npm run build            # tsc + vite — no type errors
npx prettier --check .   # formatting clean
```

Plus manual verification of:
- EditGroupDialog DnD (card→group, card→subgroup, group→group merge) still works
- Import flow DnD (all 3 operations) works correctly
- Virtualized file lists still scroll and render properly
