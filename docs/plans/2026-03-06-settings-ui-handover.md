# Settings UI Implementation Handover

**Status:** 57% Complete (Tasks 0-3 of 7 complete)
**Branch:** `feat/settings-ui`
**Worktree:** `.worktrees/settings-ui`
**Last Updated:** 2026-03-06

---

## Executive Summary

This document hands off a partially-completed Settings UI feature implementation. The foundational backend refactoring and UI scaffolding are complete. Four tasks remain: creating shared UI components, the settings draft hook, the main settings panel, and wiring it into the gallery.

**Key Accomplishments:**
- ✅ Backend refactor: Global shared executor pool for image preparation (fixes OOM risk)
- ✅ Frontend: Extracted LibraryInfoDialog, added settings button to header
- ✅ All backend tests passing (701 tests)
- ✅ All frontend tests passing for LibraryInfoDialog (11 tests)

**Remaining Work:**
- Create SettingRow and RestartBadge shared components
- Create useSettingsDraft hook with form state management
- Create SettingsPanel component with all 3 sections
- Wire SettingsPanel into Gallery and run full test suite

---

## Architecture Overview

### Backend Changes (Complete)

**Global Prepare Pool Refactoring**

The backend previously created a new `ThreadPoolExecutor` for each import job/batch combination, causing memory issues when multiple imports ran concurrently. Now uses a single system-wide pool:

- **New file:** `backend/app/services/prepare_pool.py`
  - Singleton that manages global `ThreadPoolExecutor`
  - `init_prepare_pool(max_workers)` — called at app startup from `AppSettings.max_concurrent_prepare`
  - `get_prepare_pool()` — used by ingestion code to submit tasks
  - `shutdown_prepare_pool()` — called at app shutdown

- **Modified:** `backend/pipeline/ingestion.py`
  - Two call sites (~line 910 and ~1140): removed `with ThreadPoolExecutor(...)` context manager
  - Now calls `get_prepare_pool()` directly
  - Added explicit error handling: futures are cancelled on exception to prevent zombies in shared pool

- **Modified:** `backend/app/main.py`
  - Lifespan startup: `init_prepare_pool(app_config.max_concurrent_prepare)` after seeding settings
  - Lifespan shutdown: `shutdown_prepare_pool()` before shutting down other services

- **Testing:** `backend/tests/conftest.py`
  - Added autouse fixture `prepare_pool_fixture()` that initializes pool before each test and cleans up after
  - Ensures test isolation

**Key Files:**
- `backend/app/services/prepare_pool.py` (new, 42 lines)
- `backend/tests/test_prepare_pool.py` (new, 37 lines with 3 test cases)
- `backend/pipeline/ingestion.py` (modified: removed ThreadPoolExecutor import, updated 2 call sites)
- `backend/app/main.py` (modified: added pool init/shutdown to lifespan)
- `backend/tests/conftest.py` (modified: added autouse fixture)

### Frontend Changes (Partial)

**Completed:**

1. **AppSettings Type Audit** (Task 0)
   - Added missing `max_concurrent_heavy_requests: number` field to `frontend/src/types/index.ts`
   - All 22 backend fields now present in frontend type

2. **LibraryInfoDialog Extraction** (Task 2)
   - Extracted from old `SystemInfoDialog.tsx` → new `LibraryInfoDialog.tsx`
   - Removed: grid detection toggle (moved to Settings Panel)
   - Kept: library stats, storage breakdown, location management, export, danger zone
   - Files deleted: `SystemInfoDialog.tsx`, `SystemInfoDialog.test.tsx`
   - Files created: `LibraryInfoDialog.tsx`, `LibraryInfoDialog.test.tsx` (11 passing tests)
   - Updated: `Gallery.tsx` import and component usage

3. **Settings Button & Dialog State** (Task 3)
   - Modified `frontend/src/hooks/useGalleryDialogs.ts`
     - Added: `settingsOpen: boolean` and `setSettingsOpen: (show: boolean) => void` to return type
     - Added: state variable `const [settingsOpen, setSettingsOpen] = useState(false)`
   - Modified `frontend/src/components/GalleryHeader.tsx`
     - Added: `SlidersHorizontal` icon import from lucide-react
     - Added: `onOpenSettings: () => void` prop
     - Added: settings button (SlidersHorizontal icon) between info and theme buttons
   - Modified `frontend/src/pages/Gallery.tsx`
     - Updated: GalleryHeader import from SystemInfoDialog → LibraryInfoDialog
     - Added: `onOpenSettings={() => dialogs.setSettingsOpen(true)}` prop to GalleryHeader

**Key Files:**
- `frontend/src/types/index.ts` (modified)
- `frontend/src/components/LibraryInfoDialog.tsx` (new, ~350 lines)
- `frontend/src/components/LibraryInfoDialog.test.tsx` (new, ~250 lines)
- `frontend/src/hooks/useGalleryDialogs.ts` (modified: added settings state)
- `frontend/src/components/GalleryHeader.tsx` (modified: added settings button)
- `frontend/src/pages/Gallery.tsx` (modified: wired settings button)

---

## Remaining Tasks (4/7)

### Task 4: Shared Setting Components

**Files to Create:**
- `frontend/src/components/settings/SettingRow.tsx` (~30 lines)
- `frontend/src/components/settings/RestartBadge.tsx` (~15 lines)

**SettingRow Component:**
```typescript
interface SettingRowProps {
  label: string
  description?: string
  requiresRestart?: boolean
  children: React.ReactNode
}
```

Layout:
- Label + optional description on left
- Control (input, toggle, etc.) on right
- Optional "↺ Restart to apply" badge below label
- Uses existing `section-label` CSS utility

**RestartBadge Component:**
```typescript
// Amber chip with RotateCcw icon
<span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5
  text-[10px] font-semibold uppercase tracking-wider
  bg-amber-500/10 text-amber-500 border border-amber-500/20">
  <RotateCcw className="size-2.5" />
  Restart to apply
</span>
```

**Step:** Copy the existing toggle markup from the old SystemInfoDialog (which moved to LibraryInfoDialog line ~410-430) as a template for toggle styling in SettingRow.

---

### Task 5: useSettingsDraft Hook

**File to Create:** `frontend/src/hooks/useSettingsDraft.ts` (~50 lines)

**Signature:**
```typescript
export function useSettingsDraft() {
  return {
    settings: AppSettings | undefined,         // From query
    draft: Partial<AppSettings>,               // Local edits
    setField: (key: keyof AppSettings, value: any) => void
    isDirty: boolean,                          // keys in draft > 0
    save: () => Promise<AppSettings>,          // POST patch
    discard: () => void,                       // Clear draft
    isSaving: boolean,                         // Mutation pending
  }
}
```

**Implementation Notes:**
- Use `useQuery` to fetch current settings via `settingsApi.get` with `staleTime: 30_000`
- Maintain local draft state to track user edits
- `setField`: updates draft without touching server settings
- `isDirty`: true if any keys exist in draft object
- `save()`:
  - Call `settingsApi.patch(draft)` (only sends changed fields)
  - On success: update query cache with returned settings, clear only-saved keys from draft
  - Preserve other draft keys (user might be editing while save is in-flight)
  - Show toast on success/error
- `discard()`: reset draft to `{}`

**Key Detail:** The API endpoint `PATCH /api/v1/settings/` should return the full updated settings object so we can update the query cache and clear only the fields that were actually saved.

**Tests to Write:**
- `discard()` resets draft to `{}`
- `save()` calls `settingsApi.patch` with only draft fields (not full object)
- `isDirty` is false initially, true after `setField`

---

### Task 6: SettingsPanel Component

**File to Create:** `frontend/src/components/SettingsPanel.tsx` (~250 lines)

**Props:**
```typescript
interface SettingsPanelProps {
  open: boolean
  onClose: () => void
}
```

**Structure:**

Fixed-position panel sliding in from right side (not using existing `SheetContent` which hardcodes height):

```typescript
<div
  role="dialog"
  aria-label="Configuration"
  className={cn(
    'fixed right-0 inset-y-4 z-50 flex flex-col',
    'w-[560px] rounded-l-xl',
    'bg-card border-l border-y border-border shadow-2xl',
    'transition-transform duration-300 ease-in-out',
    open ? 'translate-x-0' : 'translate-x-full',
  )}
>
  {/* Header */}
  {/* Content (3 sections) */}
  {/* Footer (Save/Discard) */}
</div>
```

**Three Sections (6 Fields Total):**

1. **General** (1 field)
   - Grid detection toggle (moved from old SystemInfoDialog)
   - Uses SettingRow + toggle markup from old SystemInfoDialog

2. **Import Limits** (4 fields)
   - Max file size (input, displayed in MB, stored in bytes)
   - Max video size (input, displayed in MB, stored in bytes)
   - Max files per import (input, integer, no unit conversion)
   - Max total upload size (input, displayed in MB, stored in bytes)
   - Uses SettingRow + `<input type="number" />` for each

3. **Performance** (1 field)
   - Concurrent imports (input, integer, 1-16 range)
   - Shows "↺ Restart to apply" badge via SettingRow `requiresRestart` prop

**Form Behavior:**

- `val(key)`: helper that returns draft value if present, else server value
- Unit conversion:
  - File sizes: display in MB, convert to/from bytes (÷ 1024² or × 1024²)
  - File counts: no conversion
- Close guard: if `isDirty && open closed`, show confirmation dialog
- Escape key: triggers close guard
- Backdrop click: triggers close guard
- `inert` attribute on content when panel closed (blocks interaction)
- `tabIndex={open ? 0 : -1}` on buttons (secondary guard for accessibility)

**Existing Components to Reuse:**
- `SettingRow` (from Task 4)
- `RestartBadge` (from Task 4)
- `ConfirmDialog` (already exists in codebase)
- Toggle markup from old SystemInfoDialog (copy exactly)
- `section-label` CSS utility class

**Tests:** None required by plan (covered by integration testing in Gallery)

---

### Task 7: Wire SettingsPanel into Gallery

**File to Modify:** `frontend/src/pages/Gallery.tsx`

**Changes:**
1. Import `SettingsPanel` from `@/components/SettingsPanel`
2. Mount component in JSX alongside LibraryInfoDialog:
   ```typescript
   <SettingsPanel
     open={dialogs.settingsOpen}
     onClose={() => dialogs.setSettingsOpen(false)}
   />
   ```
3. Run linting:
   ```bash
   cd frontend && npx tsc --noEmit && npx eslint . --fix && npx prettier --write .
   ```

**Commit:** `git commit -m "feat: wire SettingsPanel into Gallery"`

---

## Testing & Verification

### Backend
```bash
cd /worktree/settings-ui
# Run all tests
uv run pytest backend/tests/ -v --tb=short
# Should see: 701+ passed

# Format and check
uv run ruff format backend/
uv run ruff check backend/ --fix
```

### Frontend
```bash
cd /worktree/settings-ui/frontend
npm install  # if needed

# Run tests
npm test

# Type check
npx tsc --noEmit

# Lint and format
npx eslint src --fix
npx prettier --write src
```

### Manual Testing (Browser)
1. Start backend: `uv run backend.app.main:app`
2. Start frontend dev server: `cd frontend && npm run dev`
3. Open http://localhost:5173
4. Click settings button (SlidersHorizontal icon) in header
5. Verify:
   - Panel slides in from right with correct styling
   - All 6 settings fields render with correct labels/descriptions
   - Toggle works for grid detection
   - Number inputs accept values and convert units correctly
   - "Restart to apply" badge shows on concurrent imports field
   - Save button disabled when no changes
   - Changes appear in browser DevTools network tab as PATCH request
   - Close guard appears if you try to close with unsaved changes
   - Discard button clears draft without API call

---

## Key Implementation Details

### Unit Conversion
- **File sizes (MB ↔ bytes):** Use `Math.round((val) / 1024 / 1024)` and `n * 1024 * 1024`
- **File counts:** No conversion, direct integer

### Form State
- **val() helper:** Check draft first: `(key in draft ? draft[key] : settings?.[key])`
- **setField:** Partial update: `setDraft(prev => ({ ...prev, [key]: value }))`
- **isDirty:** `Object.keys(draft).length > 0`

### Close Guard Logic
```typescript
const handleClose = () => {
  if (isDirty) setConfirmClose(true)
  else onClose()
}
```

### Styling Notes
- Panel: `fixed right-0 inset-y-4` gives 16px breathing room top/bottom
- Panel width: 560px (fits comfortably on 1024px+ screens)
- Section headers: use existing `section-label` class
- Divider: thin line at `border-t border-border/50`
- Inputs: dark background with rounded corners, monospace font for numbers

---

## File Checklist

| File | Status | Notes |
|------|--------|-------|
| `backend/app/services/prepare_pool.py` | ✅ Complete | Global executor singleton |
| `backend/pipeline/ingestion.py` | ✅ Complete | Two call sites refactored |
| `backend/app/main.py` | ✅ Complete | Lifespan wired |
| `backend/tests/test_prepare_pool.py` | ✅ Complete | 3 tests passing |
| `backend/tests/conftest.py` | ✅ Complete | Autouse fixture added |
| `frontend/src/types/index.ts` | ✅ Complete | AppSettings type fixed |
| `frontend/src/components/LibraryInfoDialog.tsx` | ✅ Complete | 11 tests passing |
| `frontend/src/components/LibraryInfoDialog.test.tsx` | ✅ Complete | All tests pass |
| `frontend/src/hooks/useGalleryDialogs.ts` | ✅ Complete | Settings state added |
| `frontend/src/components/GalleryHeader.tsx` | ✅ Complete | Settings button added |
| `frontend/src/pages/Gallery.tsx` | ✅ Complete | Button wired to state |
| **`frontend/src/components/settings/SettingRow.tsx`** | ⏳ TODO | Create Task 4 |
| **`frontend/src/components/settings/RestartBadge.tsx`** | ⏳ TODO | Create Task 4 |
| **`frontend/src/hooks/useSettingsDraft.ts`** | ⏳ TODO | Create Task 5 |
| **`frontend/src/components/SettingsPanel.tsx`** | ⏳ TODO | Create Task 6 |
| `frontend/src/pages/Gallery.tsx` | ⏳ TODO | Wire SettingsPanel (Task 7) |

---

## Git Status

Current branch: `feat/settings-ui`

Recent commits:
```
b2890e4 feat: add settings button to GalleryHeader
60bb7fa refactor: extract LibraryInfoDialog from SystemInfoDialog
ad0815f refactor: make max_concurrent_prepare a global shared executor pool
```

All changes staged and committed. Ready for next agent to continue from here.

---

## Notes for Next Agent

1. **Follow the plan exactly.** The architecture and file locations are predetermined. Don't deviate.

2. **Test frequently.** After each task, run the relevant test suite and linting before moving to the next.

3. **Reuse existing patterns.**
   - Toggle markup: copy from old SystemInfoDialog or new LibraryInfoDialog
   - API patterns: use existing `settingsApi` and query structure
   - UI patterns: use `Button`, `cn()`, existing CSS utilities

4. **Use superpowers:executing-plans.** Follow the skill workflow for task-by-task execution with checkpoint reviews.

5. **Component Props & Types:** Always define TypeScript interfaces at the top of component files.

6. **Avoid Over-Engineering.** The plan is deliberately simple: 6 settings fields, 3 sections, inline component logic. No separate section files or complex abstractions.

7. **Linting:** Must pass before commit:
   - Backend: `ruff format` + `ruff check --fix`
   - Frontend: `tsc --noEmit`, `eslint --fix`, `prettier --write`

8. **When Stuck:**
   - Refer back to this document
   - Check the plan file: `docs/plans/snuggly-noodling-treasure.md`
   - Look at existing similar components (LibraryInfoDialog, TagManagementDialog, etc.)
   - The original plan has detailed code snippets and examples

---

## Contact & References

- **Plan file:** `docs/plans/snuggly-noodling-treasure.md` (original detailed plan with code examples)
- **CLAUDE.md:** Project conventions and working principles
- **Existing APIs:**
  - `settingsApi.get()` — fetch current settings
  - `settingsApi.patch(partial)` — update settings (returns full updated object)
  - `QUERY_KEYS.appSettings` — React Query key

---

**Handover completed:** 2026-03-06
**Next steps:** Pick up at Task 4 with SettingRow and RestartBadge components
