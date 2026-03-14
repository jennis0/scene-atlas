# E2E Test Expansion — Todo List

Status: ~35 tests across 10 spec files. Real test images (encrypted, Git LFS) replace procedural generation.

## Completed

### Infrastructure
- [x] Switch from procedural 40x40px images to real images (encrypted zip in repo via Git LFS)
- [x] Decrypt helper (`e2e/helpers/decrypt-fixtures.ts`) for CI and local dev
- [x] Reusable test helpers (`e2e/helpers/actions.ts`) — gallery load, import, search, filter, hover+click
- [x] `data-testid` attributes on ActivityDock, EditGroupDialog, GroupCard, FilterChips
- [x] Remove dead `confirm-review` endpoint call from seed helper
- [x] Update seed helper to support all media types (PNG, WebP, GIF, MP4, WebM)
- [x] CI config updated to pass `E2E_IMAGE_KEY` secret and checkout with LFS
- [x] Git LFS tracking for encrypted fixture file

### Upload Flow — `upload-flow.spec.ts` ✅
- [x] Upload images via import dialog → gallery count increases
- [x] Search finds uploaded images
- [x] Semantic search activates relevance mode
- [x] Filter by author shows filtered results
- [x] Image viewer shows metadata

### Gallery Deep — `gallery-deep.spec.ts` ✅
- [x] Text-only search (`=` prefix) hides relevance slider
- [x] Semantic search shows relevance controls
- [x] Filter panel opens and shows options
- [x] Applying author filter shows filter chip
- [x] Clear all removes filters and search
- [x] Empty state shows when no results match
- [x] Grouped view shows group cards
- [x] Sort dropdown changes ordering

### Edit Group — `edit-group.spec.ts` ✅
- [x] Opens from group card context menu
- [x] Shows group images and metadata
- [x] Can close dialog with escape

### Import Deep — `import-deep.spec.ts` ✅
- [x] Import dialog shows upload controls
- [x] Default type toggle is visible
- [x] File upload triggers processing

### Activity Dock — `activity-dock.spec.ts` ✅
- [x] Dock pill appears after starting import
- [x] Expanding dock shows job cards

---

## Remaining (Future Batches)

### Edit Group Deep (P1)
- [ ] Edit image name inline → auto-saves
- [ ] Change image type → auto-saves
- [ ] Add/remove tags via TagPicker
- [ ] Edit subgroup dropdown
- [ ] Delete group → confirm → removed
- [ ] Merge groups via MergeGroupPicker
- [ ] Mass-edit mode via "Edit all" button

### Import Deep Dive (P1)
- [ ] Upload unsupported file → skipped warning
- [ ] Type toggle per-file and bulk
- [ ] Cancel import → return to upload state
- [ ] Bulk select + exclude

### ImageViewer Deep (P2)
- [ ] Edit image name inline
- [ ] Change type toggle (Map/Scene)
- [ ] Add/remove tags
- [ ] Grid toggle + size inputs
- [ ] "Edit group" button → opens EditGroupDialog
- [ ] Scene sidebar navigation
- [ ] Download image

### Activity Dock Deep (P2)
- [ ] Click completed job → EditGroupDialog opens
- [ ] Dismiss/cancel jobs
- [ ] Clear completed jobs

### Tag Management (P2)
- [ ] Open from gallery header
- [ ] Create/rename/delete categories
- [ ] Add/rename/delete tag values
- [ ] Change category icon and color

### Edge Cases (P3)
- [ ] Duplicate file detection
- [ ] Video file support (badge + playback)
- [ ] ZIP upload
- [ ] Large batch virtualisation
- [ ] Browser resize responsiveness
