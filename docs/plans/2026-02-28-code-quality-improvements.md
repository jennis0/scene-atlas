# Code Quality Improvements Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix security vulnerabilities, eliminate code duplication, and improve robustness across FilterMenuContent.tsx, imports.py, and TagManagementDialog.tsx.

**Architecture:** Three independent workstreams targeting (A) backend security and maintainability in the import API, (B) frontend component cleanup in FilterMenuContent, and (C) data-loss prevention and accessibility in TagManagementDialog. Each task is self-contained and independently committable.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Vitest (frontend), Tailwind CSS

---

## Workstream A: imports.py Security & Maintainability

### Task 1: Fix path traversal guard — replace `str.startswith()` with `Path.relative_to()`

The existing path traversal guard uses `str(resolved).startswith(str(base.resolve()))` which has a known false-positive for adjacent-prefix sibling directories (documented in `test_path_traversal.py:84-106`). Replace with `Path.relative_to()` which is semantically correct.

**Files:**
- Modify: `backend/app/api/imports.py:997-1008` (preview endpoint)
- Modify: `backend/tests/unit/test_path_traversal.py:18-21, 84-106`
- Modify: `backend/tests/integration/test_preview_endpoint.py` (add traversal test)

**Step 1: Update the `_is_within_base` helper in the test file to use `relative_to()`**

In `backend/tests/unit/test_path_traversal.py`, change the helper and fix the known-limitation test:

```python
def _is_within_base(base_dir: Path, target: Path) -> bool:
    """Path containment guard using relative_to (no prefix false-positives)."""
    try:
        target.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False
```

Then update `test_adjacent_prefix_known_limitation` — it should now correctly return `False`:

```python
def test_adjacent_prefix_correctly_blocked(self, tmp_path):
    """Sibling directory with shared prefix must be blocked."""
    base_dir = tmp_path / "job1"
    sibling = tmp_path / "job1evil" / "file.jpg"
    assert _is_within_base(base_dir, sibling) is False
```

**Step 2: Run tests to verify the fix**

Run: `cd backend && python -m pytest tests/unit/test_path_traversal.py -v`
Expected: All pass, including the formerly-false-positive test now correctly blocking.

**Step 3: Create a shared `is_path_within` helper in `validation.py`**

Add to `backend/app/services/validation.py` (after the existing functions):

```python
def is_path_within(base_dir: Path, target: Path) -> bool:
    """Return True if *target* resolves to a path inside *base_dir*.

    Uses Path.relative_to() — immune to the adjacent-prefix false-positive
    that str.startswith() suffers from.
    """
    try:
        target.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False
```

**Step 4: Use `is_path_within` in imports.py preview endpoint**

In `backend/app/api/imports.py`, add the import at the top (line 43 area):

```python
from ..services.validation import check_zip_safety, is_path_within, verify_media_mime
```

Then replace the two `str(resolved).startswith(...)` checks (lines 997-1000 and 1006-1008):

```python
    if thumb_path.exists():
        if not is_path_within(staging_dir, thumb_path):
            raise HTTPException(status_code=403, detail="Access denied")
        return FileResponse(thumb_path, media_type="image/jpeg")

    # Fall back to original file
    original_path = staging_dir / relative_path
    if original_path.exists():
        if not is_path_within(staging_dir, original_path):
            raise HTTPException(status_code=403, detail="Access denied")
```

**Step 5: Add an integration test for path traversal on the preview endpoint**

Add to `backend/tests/integration/test_preview_endpoint.py`:

```python
def test_path_traversal_blocked(self, test_client, staged_with_thumbs):
    """Relative paths with ../ must be rejected."""
    job_id, _ = staged_with_thumbs
    resp = test_client.get(f"/api/v1/imports/{job_id}/preview/../../../etc/passwd")
    assert resp.status_code in (403, 404)
```

**Step 6: Run all affected tests**

Run: `cd backend && python -m pytest tests/unit/test_path_traversal.py tests/unit/test_validation.py tests/integration/test_preview_endpoint.py -v`
Expected: All pass.

**Step 7: Commit**

```bash
git add backend/app/services/validation.py backend/app/api/imports.py backend/tests/unit/test_path_traversal.py backend/tests/integration/test_preview_endpoint.py
git commit -m "Fix path traversal guard: replace str.startswith with Path.relative_to"
```

---

### Task 2: Add zip-slip protection to ZIP extraction

The `check_zip_safety` function validates file count and size but does NOT check for path traversal in ZIP member names (e.g., `../../../etc/passwd`). Python's `zipfile.extract()` has some built-in protection in 3.12+, but we should add an explicit check.

**Files:**
- Modify: `backend/app/services/validation.py:15-41`
- Modify: `backend/tests/unit/test_validation.py`

**Step 1: Write a failing test for zip-slip**

Add to `backend/tests/unit/test_validation.py` in the `TestCheckZipSafety` class:

```python
def test_zip_with_path_traversal_member_rejected(self, tmp_path):
    """ZIP member names with ../ path traversal must be rejected."""
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("../../etc/passwd")
        info.file_size = 5
        zf.writestr(info, b"evil!")
    with pytest.raises(ValueError, match="[Pp]ath traversal"):
        check_zip_safety(zip_path, max_files=10, max_uncompressed_bytes=10 * 1024 * 1024)

def test_zip_with_absolute_path_member_rejected(self, tmp_path):
    """ZIP member names with absolute paths must be rejected."""
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("/etc/passwd")
        info.file_size = 5
        zf.writestr(info, b"evil!")
    with pytest.raises(ValueError, match="[Pp]ath traversal"):
        check_zip_safety(zip_path, max_files=10, max_uncompressed_bytes=10 * 1024 * 1024)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_validation.py::TestCheckZipSafety::test_zip_with_path_traversal_member_rejected tests/unit/test_validation.py::TestCheckZipSafety::test_zip_with_absolute_path_member_rejected -v`
Expected: FAIL (no path traversal check exists yet).

**Step 3: Add path traversal check to `check_zip_safety`**

In `backend/app/services/validation.py`, update `check_zip_safety` to add a member-name check before the count/size checks:

```python
def check_zip_safety(zip_path: Path, max_files: int, max_uncompressed_bytes: int) -> None:
    try:
        with ZipFile(zip_path, "r") as zf:
            entries = zf.infolist()

            # Check for path traversal in member names
            for entry in entries:
                if entry.is_dir():
                    continue
                member = Path(entry.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(
                        f"Path traversal detected in ZIP member: {entry.filename}"
                    )

            file_count = sum(1 for e in entries if not e.is_dir())
            total_uncompressed = sum(e.file_size for e in entries if not e.is_dir())
    except BadZipFile as exc:
        raise ValueError("Invalid or corrupt ZIP file") from exc

    if file_count > max_files:
        raise ValueError(f"ZIP contains {file_count} files; limit is {max_files}")
    if total_uncompressed > max_uncompressed_bytes:
        limit_mb = max_uncompressed_bytes // (1024 * 1024)
        actual_mb = total_uncompressed // (1024 * 1024)
        raise ValueError(f"ZIP uncompressed size ({actual_mb} MB) exceeds limit of {limit_mb} MB")
```

**Step 4: Run all validation tests**

Run: `cd backend && python -m pytest tests/unit/test_validation.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add backend/app/services/validation.py backend/tests/unit/test_validation.py
git commit -m "Add zip-slip protection to check_zip_safety"
```

---

### Task 3: Consolidate duplicated `get_db` into a shared dependency

The `get_db` function is copy-pasted identically across 8 API modules. Extract it to a shared location.

**Files:**
- Create: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/imports.py:70-77` (remove local `get_db`, import shared)
- Modify: `backend/app/api/groups.py:54-61`
- Modify: `backend/app/api/images.py:29-36`
- Modify: `backend/app/api/tags.py:24-31`
- Modify: `backend/app/api/search.py:25-32`
- Modify: `backend/app/api/settings.py:13-20`
- Modify: `backend/app/api/system.py:29-36`
- Modify: `backend/app/api/export.py:46-53`

**Step 1: Create the shared dependencies module**

Create `backend/app/api/dependencies.py`:

```python
"""Shared FastAPI dependencies for API route handlers."""

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import get_session_local


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Step 2: Update each API module**

In each of the 8 API files, remove the local `get_db` definition and add:

```python
from .dependencies import get_db
```

Remove the local `get_session_local` import if it's only used by the now-removed `get_db`. For example, in `imports.py`, remove lines 70-77 and add the import from dependencies.

**Step 3: Run the full backend test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: All pass — behavior is identical, only the import path changed.

**Step 4: Commit**

```bash
git add backend/app/api/dependencies.py backend/app/api/imports.py backend/app/api/groups.py backend/app/api/images.py backend/app/api/tags.py backend/app/api/search.py backend/app/api/settings.py backend/app/api/system.py backend/app/api/export.py
git commit -m "Extract shared get_db dependency from 8 API modules"
```

---

### Task 4: Extract duplicated status-derivation logic

The effective-status calculation is duplicated between `get_import_status` (lines 692-706) and `get_active_imports` (lines 779-801). Extract into a shared helper.

**Files:**
- Modify: `backend/app/api/imports.py`

**Step 1: Extract the helper function**

Add a module-level helper above the route handlers in `imports.py`:

```python
def _derive_effective_status(
    job: ImportJob,
    group_jobs: list,
    pending_count: int,
) -> str:
    """Derive the effective import job status from its group states.

    Terminal group statuses: completed, failed, cancelled.
    """
    terminal = {"completed", "failed", "cancelled"}
    if not group_jobs:
        return job.status
    if all(gj.status in terminal for gj in group_jobs):
        if not job.all_confirmed and pending_count > 0:
            return "active"
        return "completed"
    if any(gj.status == "running" for gj in group_jobs):
        return "active"
    return job.status
```

**Step 2: Use it in both `get_import_status` and `get_active_imports`**

In `get_import_status`, replace lines 692-706 with:

```python
overall_status = _derive_effective_status(job, group_jobs, pending_count)
```

In `get_active_imports`, replace the equivalent block (lines 779-801) with:

```python
effective_status = _derive_effective_status(job, groups, pending_count)
# For completed_at, derive from group completion times
if effective_status in {"completed", "failed"}:
    completed_at = max(
        (g.completed_at for g in groups if g.completed_at),
        default=job.completed_at,
    )
else:
    completed_at = None if effective_status == "active" else job.completed_at
```

**Step 3: Run import-related tests**

Run: `cd backend && python -m pytest tests/integration/test_imports_status.py tests/integration/test_confirm_endpoint.py -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add backend/app/api/imports.py
git commit -m "Extract _derive_effective_status to DRY up status derivation"
```

---

### Task 5: Validate `image_type` form field

The upload endpoint accepts an arbitrary `image_type` string without validation.

**Files:**
- Modify: `backend/app/api/imports.py:164`
- Modify: `backend/tests/integration/test_upload_endpoint.py` (add test)

**Step 1: Write a failing test**

Add to the upload endpoint test file:

```python
def test_invalid_image_type_rejected(self, test_client):
    """Unknown image_type values must be rejected."""
    # Create a minimal JPEG for the upload
    from io import BytesIO
    from PIL import Image as PILImage
    buf = BytesIO()
    PILImage.new("RGB", (20, 20)).save(buf, format="JPEG")
    buf.seek(0)

    resp = test_client.post(
        "/api/v1/imports/upload",
        files=[("files", ("test.jpg", buf, "image/jpeg"))],
        data={"image_type": "invalid_type"},
    )
    assert resp.status_code == 422 or resp.status_code == 400
```

**Step 2: Run it to confirm it fails**

Run: `cd backend && python -m pytest tests/integration/test_upload_endpoint.py::TestUpload::test_invalid_image_type_rejected -v`
Expected: FAIL (currently any string is accepted).

**Step 3: Add validation**

In `backend/app/api/imports.py`, add validation near the top of the `upload_files` function, after parsing `manifest_entries` and before the early count guard:

```python
    VALID_IMAGE_TYPES = {"battlemap", "scene"}
    if image_type and image_type not in VALID_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image_type '{image_type}'. Must be one of: {', '.join(sorted(VALID_IMAGE_TYPES))}",
        )
```

**Step 4: Run the test**

Run: `cd backend && python -m pytest tests/integration/test_upload_endpoint.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add backend/app/api/imports.py backend/tests/integration/test_upload_endpoint.py
git commit -m "Validate image_type parameter in upload endpoint"
```

---

## Workstream B: FilterMenuContent.tsx Cleanup

### Task 6: Extract inline SVGs to a separate file

The 5 grid SVG components (~230 lines) are static presentational components that inflate FilterMenuContent.tsx.

**Files:**
- Create: `frontend/src/components/GridFilterIcons.tsx`
- Modify: `frontend/src/components/FilterMenuContent.tsx`

**Step 1: Create the new file**

Create `frontend/src/components/GridFilterIcons.tsx` and move these functions into it:
- `gridColor` (line 755)
- `SquareGridSVG` (line 761)
- `HexGridSVG` (line 825)
- `GridlessSVG` (line 879)
- `AnyGridSVG` (line 908)
- `UnknownGridSVG` (line 960)

The file should export each SVG component individually:

```typescript
export function gridColor(active: boolean, excluded: boolean): string { ... }
export function SquareGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) { ... }
// etc.
```

**Step 2: Update FilterMenuContent.tsx imports**

Replace the inline definitions with:

```typescript
import { SquareGridSVG, HexGridSVG, GridlessSVG, AnyGridSVG, UnknownGridSVG } from './GridFilterIcons'
```

Delete the `gridColor` function and all 5 SVG components from FilterMenuContent.tsx (~235 lines removed).

**Step 3: Verify the app builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

**Step 4: Commit**

```bash
git add frontend/src/components/GridFilterIcons.tsx frontend/src/components/FilterMenuContent.tsx
git commit -m "Extract grid filter SVGs to separate GridFilterIcons module"
```

---

### Task 7: Thread `getTagColor` as a prop instead of calling the hook 3 times

`useGetTagColor()` is called in `FilterMenuContent`, `CategoryNavItem`, and `OptionPill`. Since the parent already has the function, pass it down as a prop.

**Files:**
- Modify: `frontend/src/components/FilterMenuContent.tsx`

**Step 1: Add `getTagColor` prop to `CategoryNavItem`**

Change the `CategoryNavItem` component signature to accept `getTagColor` as a prop instead of calling the hook internally:

```typescript
function CategoryNavItem({
  label, active, activeCount, colorId, icon: Icon, onClick,
  getTagColor,
}: {
  // ... existing props ...
  getTagColor: (categoryName: string) => TagColor
}) {
  // Remove: const getTagColor = useGetTagColor()
  const colors = colorId ? getTagColor(colorId) : null
  // ... rest unchanged
```

**Step 2: Add `getTagColor` prop to `OptionPill`**

Same pattern — accept it as a prop, remove the internal `useGetTagColor()` call:

```typescript
function OptionPill({
  label, count, activeState, colorId, onInclude, onExclude,
  getTagColor,
}: {
  // ... existing props ...
  getTagColor: (categoryName: string) => TagColor
}) {
  // Remove: const getTagColor = useGetTagColor()
  const colors = colorId ? getTagColor(colorId) : DEFAULT_TAG_COLOR
```

**Step 3: Update all call sites in FilterMenuContent**

Pass `getTagColor` from the parent's existing hook result to each `<CategoryNavItem>` and `<OptionPill>`:

```tsx
<CategoryNavItem ... getTagColor={getTagColor} />
<OptionPill ... getTagColor={getTagColor} />
```

**Step 4: Remove the `useGetTagColor` import if it's no longer used by the child components**

Keep the single import and call in `FilterMenuContent` itself (line 127). The import from `@/contexts/TagColorContext` stays.

**Step 5: Verify the app builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

**Step 6: Commit**

```bash
git add frontend/src/components/FilterMenuContent.tsx
git commit -m "Thread getTagColor as prop to avoid redundant context hook calls"
```

---

### Task 8: Guard `loadCustomColors` against SSR/missing localStorage

The `useState` initializer calls `localStorage.getItem` synchronously, which throws outside browser contexts.

**Files:**
- Modify: `frontend/src/components/FilterMenuContent.tsx:1126-1133`

**Step 1: Add a typeof guard**

Update `loadCustomColors`:

```typescript
function loadCustomColors(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const stored = localStorage.getItem(CUSTOM_COLORS_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}
```

**Step 2: Verify the app builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/components/FilterMenuContent.tsx
git commit -m "Guard loadCustomColors against missing localStorage"
```

---

## Workstream C: TagManagementDialog.tsx Improvements

### Task 9: Save description on dialog close, not just on blur

If a user types a description and closes the dialog without blurring the textarea, the change is lost.

**Files:**
- Modify: `frontend/src/components/TagManagementDialog.tsx`

**Step 1: Add a ref to track unsaved description state**

The `CategoryEditor` component uses local `description` state. The issue is that `handleDescSave` only fires on blur. We need to fire it when the component unmounts (i.e., when the dialog closes or the user switches categories, since `CategoryEditor` is keyed on `effectiveSelection`).

In `CategoryEditor`, add a cleanup effect:

```typescript
// Inside CategoryEditor, after the handleDescSave definition:

// Save unsaved description on unmount (dialog close or category switch)
const descriptionRef = useRef(description)
descriptionRef.current = description

const categoryDescRef = useRef(category.description ?? '')
categoryDescRef.current = category.description ?? ''

useEffect(() => {
  return () => {
    const current = descriptionRef.current.trim()
    const original = categoryDescRef.current
    if (current !== original) {
      updateMut.mutate({ description: current || undefined })
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [])
```

The refs are needed because the cleanup function must read the latest value without being re-registered on every keystroke.

**Step 2: Verify the app builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/components/TagManagementDialog.tsx
git commit -m "Save unsaved description on CategoryEditor unmount"
```

---

### Task 10: Replace ConfirmOverlay with ConfirmDialog

The custom `ConfirmOverlay` component (lines 964-996) lacks focus trapping and keyboard handling. The project already has a `ConfirmDialog` component (`frontend/src/components/ui/confirm-dialog.tsx`) that uses the Dialog primitive and is the established pattern elsewhere (e.g., in EditGroupDialog). Replace the custom overlay.

**Files:**
- Modify: `frontend/src/components/TagManagementDialog.tsx`

**Step 1: Replace `ConfirmOverlay` usage with `ConfirmDialog`**

Import `ConfirmDialog` at the top of the file:

```typescript
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
```

Replace the `ConfirmOverlay` render block (near line 224-226):

```tsx
{/* Old: */}
{confirmAction && (
  <ConfirmOverlay action={confirmAction} onCancel={() => setConfirmAction(null)} />
)}

{/* New: */}
<ConfirmDialog
  open={confirmAction !== null}
  onOpenChange={(open) => { if (!open) setConfirmAction(null) }}
  title={confirmAction?.label ?? ''}
  description={confirmAction?.detail ?? ''}
  confirmLabel={confirmAction?.confirmLabel ?? 'Delete'}
  confirmVariant={confirmAction?.confirmStyle === 'warning' ? 'default' : 'destructive'}
  onConfirm={() => confirmAction?.onConfirm()}
/>
```

Note: The `ConfirmDialog` must be rendered **outside** the `DialogContent` of the parent dialog (move it after the closing `</Dialog>` tag, or wrap it in a portal). Check the existing pattern in EditGroupDialog — `ConfirmDialog` instances are placed as siblings after the main `<Dialog>`.

**Step 2: Delete the `ConfirmOverlay` component and the `ConfirmAction` type**

Remove the entire `ConfirmOverlay` function (lines 964-996). Keep the `ConfirmAction` type if it's still useful for the state management, or simplify the state to match ConfirmDialog's props directly.

**Step 3: Verify the app builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

**Step 4: Commit**

```bash
git add frontend/src/components/TagManagementDialog.tsx
git commit -m "Replace custom ConfirmOverlay with ConfirmDialog for focus management"
```

---

### Task 11: Add `console.warn` to `parseCommonValues` for malformed JSON

Silent error swallowing makes debugging harder when tag vocabulary data is corrupted.

**Files:**
- Modify: `frontend/src/components/TagManagementDialog.tsx:24-36`

**Step 1: Add a warning to the catch block**

```typescript
function parseCommonValues(raw: string | null): TagValueEntry[] {
  if (!raw) return []
  try {
    const arr = JSON.parse(raw) as (string | { value: string; aliases?: string[] })[]
    return arr.map((v) =>
      typeof v === 'string'
        ? { value: v, aliases: [] }
        : { value: v.value, aliases: v.aliases ?? [] },
    )
  } catch (e) {
    console.warn('Failed to parse common_values JSON:', e)
    return []
  }
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/TagManagementDialog.tsx
git commit -m "Warn on malformed common_values JSON instead of silent swallow"
```

---

## Summary

| Task | Workstream | Severity | Description |
|------|-----------|----------|-------------|
| 1 | A | **Security** | Fix path traversal: `str.startswith` → `Path.relative_to` |
| 2 | A | **Security** | Add zip-slip member name validation |
| 3 | A | Maintainability | Consolidate 8 duplicate `get_db` functions |
| 4 | A | Maintainability | Extract duplicated status-derivation logic |
| 5 | A | Correctness | Validate `image_type` parameter |
| 6 | B | Maintainability | Extract SVGs to separate file (~230 lines) |
| 7 | B | Efficiency | Thread `getTagColor` as prop (3 hook calls → 1) |
| 8 | B | Robustness | Guard `loadCustomColors` for non-browser environments |
| 9 | C | **Data loss** | Save description on unmount, not just blur |
| 10 | C | Accessibility | Replace ConfirmOverlay with focus-trapping ConfirmDialog |
| 11 | C | Debuggability | Warn on malformed JSON in parseCommonValues |

**Recommended order:** Tasks 1-2 first (security), then 9 (data loss), then remaining tasks in any order. Tasks are independent and can be parallelized across workstreams.
