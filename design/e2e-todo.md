# E2E Test Expansion — Todo List

Status: 15 tests across 5 spec files complete (smoke, gallery, search, image-viewer, import basics). This tracks the remaining ~85 tests across 7 new spec files.

## Batch 1: Import Deep Dive — `import-deep.spec.ts` (P1)

The import pipeline is the most complex and bug-prone flow. Priority 1.

- [ ] Upload multiple files via file chooser → correct group count in preview
- [ ] Default type toggle: set to Scene before upload → all files typed as scene
- [ ] Upload unsupported file → skipped-files warning appears
- [ ] Skip group → strikethrough + "Undo" visible; unskip restores
- [ ] Exclude file → greyed + "Restore"; restore brings it back
- [ ] Edit author on single group → value persists when switching tabs
- [ ] Edit author on "All" tab → sets across all groups
- [ ] Edit group name → value persists
- [ ] Set subgroup on file → SubgroupDropdown → pick/type value
- [ ] Swap file type map↔scene → toggle reflects new type
- [ ] Bulk select + type change → all selected files change type
- [ ] Bulk select + exclude → all selected files excluded
- [ ] Split group → new group appears in nav with selected files
- [ ] Merge two groups → source removed, files appear in target
- [ ] Merge all → confirm dialog → single group remains
- [ ] Text filter → cards filter by name
- [ ] Import single group → only that group shows progress/completed
- [ ] Cancel import → return to upload state

**Note**: Drag-and-drop upload is skipped — Playwright can't reliably simulate `DataTransferItem`/`FileSystemEntry` recursive folder traversal. Covered by Browse buttons instead.

## Batch 2: EditGroup Dialog — `edit-group.spec.ts` (P1)

EditGroup uses richer `FileCard` (not `ImportFileCard`) with inline name editing, grid controls, tag management, and drag-and-drop between groups/subgroups. Three modes: single-group, mass-edit, import-review.

- [ ] Open from GroupCard "..." menu → dialog shows group files
- [ ] Edit image name inline → save indicator appears (spinner → check)
- [ ] Change image type → auto-saves
- [ ] Change grid toggle and grid size → auto-saves
- [ ] Add tag via TagPicker → tag pill appears on image
- [ ] Remove tag via X → tag pill disappears
- [ ] Edit subgroup via dropdown → value changes
- [ ] Rename subgroup heading → all files in subgroup update
- [ ] Delete group → footer "Delete group" → confirm → group removed, dialog closes
- [ ] Merge into → footer "Merge into..." → MergeGroupPicker → select → merge completes
- [ ] Open via "Edit all (N)" button → mass-edit mode shows all search results
- [ ] Multi-group select in sidebar (Ctrl+click) → bulk merge/delete buttons appear
- [ ] Drag file to different group in sidebar → file moves (API: `groupApi.moveImages`)
- [ ] Drag file to subgroup heading → subgroup changes
- [ ] Filter bar: text filter, type toggle, filter popover (subgroup, grid, tags)

**Note**: EditGroup can also be opened from ImageViewer ("Edit group" button) and ActivityDock (completed job click) — tested in Batches 4 and 5 respectively.

## Batch 3: Gallery Filters & Search — `gallery-deep.spec.ts` (P1)

The gallery has rich search modes, filter dimensions, and group-level operations via the GroupCard context menu.

- [ ] Text-only search (`=` prefix) → AlignLeft icon, no relevance slider shown
- [ ] Relevance sort: submit search → Relevance option enables → select it
- [ ] Relevance slider: semantic search → drag slider → result count changes
- [ ] Open filter popover → click author filter → chip appears below → results filter
- [ ] Remove filter chip via X → results restore
- [ ] Filter exclude mode: right-click filter option → strikethrough red pill, results exclude
- [ ] Clear all: apply search + filters → "Clear all" button → everything resets
- [ ] Empty state: search gibberish → "No images match" message + "Clear search" button
- [ ] GroupCard menu → Edit → EditGroupDialog opens for that group
- [ ] GroupCard menu → Merge into → MergeGroupPicker → select target → merge completes
- [ ] GroupCard menu → Delete → confirm → group removed from gallery
- [ ] GroupCard menu → Download → ZIP file downloads

**Note**: Filter popover supports Author, Grid (square/hex/any/gridless/unknown), Media type, Color (palette), and Tag categories. Right-click = exclude, left-click = include.

## Batch 4: ImageViewer Deep — `image-viewer-deep.spec.ts` (P2)

The viewer sidebar has inline-editable fields with auto-save, tag management, and a scene navigation panel for grouped images.

- [ ] Edit image name inline → click name → input appears → type → Enter saves
- [ ] Change type toggle (Map/Scene) → auto-saves via PATCH
- [ ] Edit subgroup via SubgroupDropdown → saves
- [ ] Add tag via TagPicker "+" button → tag pill appears
- [ ] Remove tag via X on tag pill → tag disappears
- [ ] Grid toggle + grid size inputs (for battlemaps only)
- [ ] Delete image → Trash2 → ConfirmDialog → image deleted, viewer navigates to next
- [ ] Download image button → file downloads
- [ ] "Edit group" button → viewer closes, EditGroupDialog opens
- [ ] Scene sidebar: click different scene tile → viewer switches to that image
- [ ] Scene sidebar filter: text filter + type toggle filter scenes
- [ ] Prev/next chevron buttons navigate between images
- [ ] Color swatches display correctly (read-only check)

## Batch 5: ActivityDock — `activity-dock.spec.ts` (P2)

Integration-heavy — triggers real imports and waits for background processing. Needs higher timeout budget.

- [ ] Start import → dock pill appears bottom-right with spinner badge
- [ ] Expand dock → job card visible with progress bar
- [ ] Click active job card → ImportDialog reopens for that job
- [ ] Wait for processing completion → job card shows "completed" state
- [ ] Click completed job → EditGroupDialog opens (import-review mode)
- [ ] Dismiss completed job → hover X button → job removed from list
- [ ] Cancel active job → hover cancel X button → job shows cancelled state
- [ ] Clear completed → Trash2 "Clear completed" header button → all terminal jobs removed
- [ ] All jobs dismissed → dock disappears entirely

## Batch 6: Tag Management — `tag-management.spec.ts` (P2)

TagManagementDialog has category CRUD, value CRUD, aliases, icon/color customization, and auto-tag regeneration.

- [ ] Open TagManagementDialog from "Manage Tags" gallery header button
- [ ] Create new category → appears in left panel list
- [ ] Add tag value to category → appears in value list
- [ ] Rename category → click name → inline edit → name updates
- [ ] Rename tag value → click value → inline edit → name updates
- [ ] Add alias to tag value → alias chip appears
- [ ] Remove alias → X on chip → alias disappears
- [ ] Delete tag value → Trash2 → confirm (if images use it) → removed
- [ ] Delete category → Trash2 → confirm → category + all values removed
- [ ] Change category icon and color via popover → icon/color update
- [ ] "Regenerate auto-tags" button → confirm → background job runs (poll via useJobPolling)

## Batch 7: Edge Cases & Stability — `edge-cases.spec.ts` (P3)

Stress tests and unusual flows.

- [ ] Rapid type toggling (10x) on import card → final state is correct
- [ ] Close import during preview → reopen → state preserved via localStorage
- [ ] Upload duplicate files → duplicate badges appear → skip/import toggles work
- [ ] Upload video file → video badge in gallery, video plays in viewer lightbox
- [ ] ZIP upload → files extracted server-side and grouped correctly
- [ ] Large batch (generate 50+ images) → virtualised grid renders correctly
- [ ] Browser resize → gallery columns adjust responsively

## Infrastructure Tasks

These are needed before certain batches can be implemented:

- [ ] Update `generate_e2e_images.py` to produce a minimal MP4 for video tests (Batch 7)
- [ ] Create a minimal `.zip` fixture for ZIP upload tests (Batch 7)
- [ ] Add test data seeding for multiple groups (needed for Batch 2 merge/multi-group tests)
- [ ] Verify Playwright `dragTo()` works with the app's `onDragStart`/`onDrop` handlers (Batch 2)
- [ ] Verify right-click via `page.click(selector, { button: 'right' })` works for filter exclude (Batch 3)

## Summary

| Batch | Spec file | Tests | Priority | Status |
|---|---|---|---|---|
| Existing | smoke, gallery, search, image-viewer, import | 15 | Done | ✅ |
| 1. Import Deep | `import-deep.spec.ts` | 18 | P1 | ⬜ |
| 2. EditGroup | `edit-group.spec.ts` | 15 | P1 | ⬜ |
| 3. Gallery Deep | `gallery-deep.spec.ts` | 12 | P1 | ⬜ |
| 4. ImageViewer Deep | `image-viewer-deep.spec.ts` | 13 | P2 | ⬜ |
| 5. ActivityDock | `activity-dock.spec.ts` | 9 | P2 | ⬜ |
| 6. Tag Management | `tag-management.spec.ts` | 11 | P2 | ⬜ |
| 7. Edge Cases | `edge-cases.spec.ts` | 7 | P3 | ⬜ |
| **Total** | **12 files** | **~100** | | |
