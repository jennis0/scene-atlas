# Import Preview UX — Remaining Work

## Code Cleanup (no new features, no UI changes)

- [x] Remove unused `Badge` import from `frontend/src/components/ImportDialog.tsx`
- [x] Fix `Search.tsx:46` bug — `setResults` should be `setSelectedImage` (pre-existing, not from our changes)
- [x] Delete dead code — `backend/flows/tasks/metadata_extraction.py` (`extract_metadata_from_upload` was never called). Removed file and its export from `backend/flows/tasks/__init__.py`. Also added `generate_preview_thumbnail` to the package exports.
- [x] Run TypeScript compilation (`npx tsc --noEmit` in `frontend/`) — compiles clean
- [x] Update `design/web-import.md` to match current code
- [x] Update `design/ingestion.md` to match current code
- [x] Staging cleanup — documented as known limitation in both design docs (three options listed)

## Feature Testing (from existing plan, nothing new)

- [ ] End-to-end: Upload a folder → thumbnails appear in preview
- [ ] End-to-end: Edit tags (remove, add) → confirm → DB records reflect edits
- [ ] End-to-end: Toggle grid status → confirm → DB has user's choice
- [ ] End-to-end: Exclude a file → confirm → it's not processed
- [ ] End-to-end: Skip a group → Import All → skipped group not submitted
- [ ] End-to-end: Merge two groups → confirm → combined files processed as one
- [ ] End-to-end: Zip upload path
- [ ] End-to-end: Single group (no tab bar should appear)
- [ ] End-to-end: Default author bar (empty author → apply default)

## Deferred

- [ ] Dark mode — ImportDialog uses hardcoded light colors, needs `dark:` variants
