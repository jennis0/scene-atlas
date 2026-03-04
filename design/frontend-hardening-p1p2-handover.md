# Frontend Hardening Phase 2 — Handover

**Branch:** `worktree-frontend-hardening-p1p2`
**Date:** 2026-03-04
**Commits:** 4

## What Was Done

### Phase 1: Security Fixes (Priority 1)

**1a. Frozen `window.__SCENE_ATLAS_PORT__`**
- `DesktopGate.tsx` now uses `Object.defineProperty` with `writable: false, configurable: true`
- `configurable: true` was chosen over `false` because vitest strict mode throws on `delete` of non-configurable properties — the existing test cleanup pattern needed to keep working
- The main threat (accidental `window.__SCENE_ATLAS_PORT__ = x` assignment) is still blocked

**1b. CSP documentation**
- Added HTML comment in `index.html` above the CSP meta tag explaining why `http://localhost:*` is in `connect-src` (needed for Electron file:// origin)

**1c. Input length limits**
- Added `MAX_AUTHOR_LENGTH` (256) and `MAX_NAME_LENGTH` (512) constants to `constants.ts`
- Applied `maxLength` to all 5 user-facing text inputs:
  - `MetadataForm.tsx` — author, groupName
  - `ImageViewer.tsx` — nameDraft
  - `FileCard.tsx` — nameDraft
  - `SubgroupDropdown.tsx` — draft

### Phase 2a: Query Key Centralization (Priority 2)

- Created `frontend/src/lib/queryKeys.ts` with:
  - `QUERY_KEYS` object — typed constants/factory functions for all 9 query key patterns
  - `invalidateGalleryQueries()` — invalidates search + searchFacets + images
  - `invalidateTagQueries()` — invalidates tagCategories + searchFacets
- Migrated all 12 files that had inline query key literals
- Zero inline `queryKey: ['...']` patterns remain in the codebase

### Phase 2b: API Module Split (Priority 2)

- Split the monolithic 442-line `api.ts` into domain modules under `frontend/src/lib/api/`:
  - `_client.ts` — axios instance + base URL interceptor
  - `imageApi.ts`, `searchApi.ts`, `tagApi.ts`, `importApi.ts`, `groupApi.ts`, `jobApi.ts`, `systemApi.ts`, `settingsApi.ts`
  - `urls.ts` — thumbnail/image/download URL helpers
  - `index.ts` — barrel re-export
- All 32 consumer files needed **zero import changes** thanks to the barrel pattern

### Phase 2c: Coverage Threshold (Priority 2)

- Raised vitest line coverage threshold from 10% to 20% (actual coverage: ~25%)

## Verification

All checks pass:
- `npm run build` — clean (tsc + vite)
- `npm run lint` — 0 errors, 0 warnings
- `npm run test` — 248/248 tests pass
- `npm audit` — 0 vulnerabilities

## What Was NOT Done (Deferred — Priority 3)

These items from the original handover remain for a future session:

1. **Tailwind CSS v4 migration** — Major breaking change (PostCSS → Vite plugin, `@apply` → `@theme`, utility renames). Requires dedicated session.
2. **ESLint 9+ / flat config** — Current ESLint 8 is deprecated but functional. Migration requires rewriting all config to flat format.
3. **React 19 upgrade** — Blocked by `@dnd-kit` compatibility. Wait for `@dnd-kit` React 19 support or evaluate alternatives (`@atlaskit/pragmatic-drag-and-drop`).
4. **Electron session-level CSP** — Narrow `connect-src` from `http://localhost:*` to the exact backend port using Electron's `session.webRequest` API.

## Files Modified

```
frontend/index.html                              (CSP comment)
frontend/vitest.config.ts                        (coverage threshold)
frontend/src/lib/constants.ts                    (input length constants)
frontend/src/lib/queryKeys.ts                    (NEW — centralized query keys)
frontend/src/lib/api/                            (NEW — 11 domain modules)
frontend/src/lib/api.ts                          (DELETED — replaced by api/)
frontend/src/components/DesktopGate.tsx           (port freeze)
frontend/src/components/ImageViewer.tsx           (maxLength + query keys)
frontend/src/components/EditGroupDialog.tsx       (query keys)
frontend/src/components/ImportDialog.tsx          (query keys)
frontend/src/components/SystemInfoDialog.tsx      (query keys)
frontend/src/components/TagManagementDialog.tsx   (query keys)
frontend/src/components/GalleryFilterPanel.tsx    (query keys)
frontend/src/components/MergeGroupPicker.tsx      (query keys)
frontend/src/components/SubgroupDropdown.tsx      (maxLength)
frontend/src/components/import/MetadataForm.tsx   (maxLength)
frontend/src/components/import/FileCard.tsx       (maxLength)
frontend/src/contexts/TagColorContext.tsx         (query keys)
frontend/src/hooks/useGalleryDialogs.ts          (query keys)
frontend/src/hooks/useGallerySearch.ts           (query keys)
frontend/src/pages/Gallery.tsx                   (query keys)
```
