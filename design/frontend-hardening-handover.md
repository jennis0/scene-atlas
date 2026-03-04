# Frontend Hardening — Handover Document

**Date**: 2026-03-04
**Branch**: `feature/frontend-hardening` (merged to main after this session)
**Session scope**: Security review, dependency upgrades, and frontend maintainability improvements

---

## What Was Done This Session

### 1. Frontend Review (analysis only)
A full frontend review identified improvements across security, performance, and maintainability. All findings are captured in this document.

### 2. Dependency Upgrades ✅ COMMITTED

All safe stable-release upgrades have been applied. `npm audit` now reports **0 vulnerabilities**.

| Package | From | To | Reason |
|---------|------|----|--------|
| vite | 5.0.11 | 7.3.1 | Fixes esbuild dev-server CVE (GHSA-67mh-4wv8-2f99) |
| @vitejs/plugin-react | 4.x | 5.1.4 | Companion to Vite 7 |
| @typescript-eslint/eslint-plugin | 6.21.0 | 8.56.1 | Fixes minimatch ReDoS (HIGH) |
| @typescript-eslint/parser | 6.21.0 | 8.56.1 | Same as above |
| eslint-plugin-react-hooks | 4.6.2 | 7.0.1 | Latest stable |
| jsdom | 26.x | 28.x | Test environment update |
| autoprefixer, postcss, axios | various | latest patch | Routine patch updates |
| @tanstack/react-virtual | 3.13.18 | 3.13.19 | Patch |
| @testing-library/dom | missing | 10.x | Was a missing peer dep causing test failures |

**Config change**: `.eslintrc.cjs` has 4 new `"off"` rules for react-hooks v7 false positives:
- `react-hooks/refs` — endorses a well-established "latest ref" pattern React docs support
- `react-hooks/static-components` — flags icon registry lookups as false positives
- `react-hooks/set-state-in-effect` — overly strict for init/prop-sync use cases
- `react-hooks/incompatible-library` — false positive from @tanstack/react-virtual

---

## Remaining Work

### Priority 1: Quick Security/Robustness Fixes (1–2 hours)

These are small, isolated changes — ideal to tackle first or in parallel.

#### 1a. Freeze `window.__SCENE_ATLAS_PORT__`

**File**: `frontend/src/components/DesktopGate.tsx` (~line 31)

**Problem**: The global is assigned as a plain property, so any script running after `DesktopGate` mounts could overwrite it and redirect all API calls.

**Fix**: Replace assignment with `Object.defineProperty`:
```ts
// Before
window.__SCENE_ATLAS_PORT__ = port

// After
Object.defineProperty(window, '__SCENE_ATLAS_PORT__', {
  value: port,
  writable: false,
  configurable: false,
})
```

The type in `frontend/src/electron.d.ts` already declares it `readonly` — no type change needed.

#### 1b. Document CSP limitation

**File**: `frontend/index.html`

Add a comment above the CSP meta tag explaining why `http://localhost:*` is in `connect-src`:

```html
<!-- connect-src includes http://localhost:* because in Electron mode the app
     runs under file:// origin, so 'self' does not cover localhost API calls.
     Narrowing this requires Electron session-level CSP override (separate task).
     In server/web mode, 'self' covers the backend; the wildcard is harmless
     since script-src 'self' prevents any XSS that could exploit it. -->
```

#### 1c. Client-side input length limits

**Problem**: Text inputs have no `maxLength`, so users (or attackers) could submit very large payloads. Server validates, but client enforcement is a good defense-in-depth.

**Limits**: 256 chars for author names, 512 chars for everything else (group names, image names, subgroup names).

**Add to `frontend/src/lib/constants.ts`**:
```ts
export const MAX_AUTHOR_LENGTH = 256
export const MAX_NAME_LENGTH = 512
```

**Files to update** (add `maxLength` attribute to `<input>` elements):

| File | Field | Limit constant |
|------|-------|---------------|
| `frontend/src/components/MetadataForm.tsx` | author input | `MAX_AUTHOR_LENGTH` |
| `frontend/src/components/MetadataForm.tsx` | groupName input | `MAX_NAME_LENGTH` |
| `frontend/src/components/ImageViewer.tsx` | nameDraft input (~line 96) | `MAX_NAME_LENGTH` |
| `frontend/src/components/import/FileCard.tsx` | name input (~line 42) | `MAX_NAME_LENGTH` |
| `frontend/src/components/import/SubgroupDropdown.tsx` | draft input (~line 82) | `MAX_NAME_LENGTH` |

No character counter UI needed — `maxLength` silently enforces the limit via the browser.

---

### Priority 2: Maintainability Refactors (3–5 hours)

These are larger but purely mechanical changes with no behaviour impact.

#### 2a. Centralize query invalidation

**Problem**: `queryClient.invalidateQueries()` calls are duplicated across 8+ files with slightly different key sets, meaning a missed invalidation shows stale UI silently.

**Solution**: Create `frontend/src/lib/queryKeys.ts`:

```ts
import { QueryClient } from '@tanstack/react-query'

export const QUERY_KEYS = {
  search: ['search'] as const,
  searchFacets: ['searchFacets'] as const,
  images: ['images'] as const,
  tagCategories: ['tagCategories'] as const,
  scenes: (id: string) => ['scenes', id] as const,
  image: (id: string) => ['image', id] as const,
  systemInfo: ['system-info'] as const,
}

/** Invalidates all queries affected by changes to the scene library (add/edit/delete). */
export function invalidateGalleryQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.images })
}
```

**Files to migrate** (grep for `invalidateQueries` to find all call sites):
- `frontend/src/pages/Gallery.tsx`
- `frontend/src/hooks/useGalleryDialogs.ts`
- `frontend/src/components/EditGroupDialog.tsx`
- `frontend/src/components/ImageViewer.tsx`
- `frontend/src/components/ImportDialog.tsx`
- `frontend/src/components/MergeGroupPicker.tsx`
- `frontend/src/components/TagManagementDialog.tsx`
- `frontend/src/components/SystemInfoDialog.tsx`

Also migrate `queryKey` literals in the query hooks that define them (e.g., `useGallerySearch.ts`, `useBackgroundJobs.ts`) to use `QUERY_KEYS.*`.

#### 2b. Split `api.ts` into domain files

**Problem**: `frontend/src/lib/api.ts` is 442 lines covering 8 unrelated API domains in one file. Growing this file increases merge conflict risk and makes navigation harder.

**Strategy**: Use a barrel `index.ts` so the 27 files importing from `@/lib/api` need **zero changes** — TypeScript/Vite resolves `@/lib/api` to `@/lib/api/index.ts` automatically.

**New structure**:
```
frontend/src/lib/api/
├── index.ts          ← barrel: re-exports everything from domain files
├── _client.ts        ← axios instance + interceptor (private)
├── imageApi.ts
├── searchApi.ts
├── tagApi.ts
├── importApi.ts
├── groupApi.ts
├── jobApi.ts
├── systemApi.ts
├── settingsApi.ts
└── urls.ts           ← getThumbnailUrl, getImageUrl, getGroupDownloadUrl, etc.
```

**Steps**:
1. Create `frontend/src/lib/api/` directory
2. Move content from `api.ts` into the respective domain files
3. Write barrel `index.ts` re-exporting all public symbols
4. Delete `frontend/src/lib/api.ts`
5. Run `npm run build` and `npm run test` to verify — no consumer changes needed

#### 2c. Raise test coverage threshold

**File**: `frontend/vitest.config.ts`

Current threshold is 10% (too low to catch regressions). Run `npm run test:coverage` to see the actual current coverage, then set the threshold to (actual − 5%) rounded down to the nearest 5. Expected target: 40–50%.

---

### Priority 3: Major Ecosystem Upgrades (separate branch per item)

These are **not** small changes. Each one requires its own branch, careful migration, and full regression testing. Defer until the priority 1/2 work is merged.

#### 3a. Tailwind CSS 3 → 4

Tailwind 4 is a complete rewrite with a CSS-first config approach. `tailwind.config.js` would be entirely replaced by CSS variables in `index.css`. Many utility class names have changed. Migration guide: https://tailwindcss.com/docs/v4-beta (now stable).

`tailwind-merge` must also be upgraded from v2 → v3 at the same time (breaking API changes).

#### 3b. ESLint 8 → 10

ESLint 9/10 uses a flat config format (`eslint.config.js`) instead of `.eslintrc.cjs`. All plugins must support the flat config API. Most do as of early 2026. After upgrading ESLint:
- `eslint-plugin-react-refresh` can be upgraded from 0.4.26 → 0.5.2 (currently pinned due to ESM-only in 0.5.x requiring flat config)
- The `.eslintrc.cjs` must be converted to `eslint.config.js`

#### 3c. React 18 → 19

React 19 has breaking changes around `forwardRef`, `act()` test wrapping, context API, and removed APIs. The codebase uses React 18 patterns throughout. Key things to check:
- All `forwardRef` usages (React 19 makes ref a regular prop)
- Test `act()` warnings (currently pre-existing in DesktopGate.test.tsx)
- Third-party library compatibility (all Radix UI components must support React 19)

`@types/react` and `@types/react-dom` must be updated from 18 → 19 in lockstep.

#### 3d. React Router 6 → 7

React Router 7 can run in "library mode" (similar to v6 API) or "framework mode" (Remix-style). Library mode migration is lower effort but still requires review of all `useNavigate`, `Route`, `Link` usages. The codebase currently has only one route (`/` → Gallery), so this should be low risk. Check the [React Router v7 migration guide](https://reactrouter.com/upgrading/v6).

#### 3e. lucide-react 0.307 → 0.577

Many icon names were renamed or removed between 0.307 and 0.577. After upgrading, run a TypeScript build — it will report all missing named imports. A grep for all `from 'lucide-react'` imports followed by comparing to the new icon list will surface everything that needs renaming.

---

## Files Quick Reference

| File | What's relevant |
|------|----------------|
| `frontend/src/components/DesktopGate.tsx` | Port global freeze (task 1a) |
| `frontend/index.html` | CSP comment (task 1b) |
| `frontend/src/lib/constants.ts` | Add MAX_AUTHOR_LENGTH, MAX_NAME_LENGTH (task 1c) |
| `frontend/src/components/MetadataForm.tsx` | maxLength on author + groupName (task 1c) |
| `frontend/src/components/ImageViewer.tsx` | maxLength on name edit (task 1c) |
| `frontend/src/components/import/FileCard.tsx` | maxLength on name (task 1c) |
| `frontend/src/components/import/SubgroupDropdown.tsx` | maxLength on subgroup name (task 1c) |
| `frontend/src/lib/queryKeys.ts` | New file to create (task 2a) |
| `frontend/src/lib/api.ts` | Split into `api/` directory (task 2b) |
| `frontend/vitest.config.ts` | Coverage threshold (task 2c) |
| `frontend/.eslintrc.cjs` | 4 new off-rules from react-hooks v7 (already committed) |

## Verification Checklist (after each task group)

```bash
cd frontend
npm run build       # TypeScript + Vite build — must be clean
npm run lint        # ESLint -- 0 errors, 0 warnings
npm run test        # 248 tests must all pass (248 is baseline)
npm audit           # Must report 0 vulnerabilities
```
