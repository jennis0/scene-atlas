# Grouped View Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add relevance slider filtering and Edit All functionality to grouped view, completing the search groups feature.

**Architecture:**
- **Relevance Slider:** Extend useGroupSearch to accept minScore parameter; filter groups client-side when raising threshold (instant), debounce 400ms when lowering threshold (refetch from page 0)
- **Edit All:** When grouped view has ≤100 groups and Edit All is clicked, fetch all matching images via /api/v1/search with limit=2000, pass as seedImages to EditGroupDialog
- **Testing:** Verify all existing tests pass (670+), manual testing of slider UX and Edit All flow

**Tech Stack:** React Query (useInfiniteQuery), TypeScript, Tailwind, pytest, ESLint, Prettier

---

## Task 1: Add minScore filtering to useGroupSearch

**Files:**
- Modify: `frontend/src/hooks/useGroupSearch.ts`

**Step 1: Update useGroupSearch signature and add minScore parameter**

Replace the entire `useGroupSearch` function with this version that accepts `minScore`:

```typescript
export function useGroupSearch(
  params: Omit<SearchParams, 'limit' | 'offset'>,
  minScore: number = 0,
) {
  const query = useInfiniteQuery<GroupSearchResponse>({
    queryKey: [QUERY_KEYS.groups, params],
    queryFn: ({ pageParam = 0 }) =>
      searchApi.groups({ ...params, limit: PAGE_SIZE, offset: pageParam as number }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const fetched = (lastPage.offset ?? 0) + PAGE_SIZE
      return fetched < lastPage.total_groups ? fetched : undefined
    },
  })

  // Flatten all pages into a single groups array
  const groups = useMemo(
    () =>
      query.data?.pages
        .flatMap((p) => p.groups)
        .map(toImageGroup)
        .filter((g) => g.bestScore === null || g.bestScore >= minScore) ?? [],
    [query.data?.pages, minScore],
  )

  // Total groups across all fetches (from first page)
  const totalGroups = query.data?.pages[0]?.total_groups ?? 0

  return {
    ...query,
    groups,
    totalGroups,
  }
}
```

**Step 2: Verify the changes compile**

Run: `cd frontend && npm run type-check`
Expected: No TypeScript errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useGroupSearch.ts
git commit -m "feat: add minScore filtering to useGroupSearch hook"
```

---

## Task 2: Update useGallerySearch to pass minScore to useGroupSearch

**Files:**
- Modify: `frontend/src/hooks/useGallerySearch.ts`

**Step 1: Find where useGroupSearch is called**

Search for: `useGroupSearch(` in the file. Note the current call location (should be around line 240-250).

**Step 2: Update useGroupSearch call to pass minScore**

Replace the useGroupSearch call from:
```typescript
const groupSearch = useGroupSearch(groupSearchParams)
```

To:
```typescript
const groupSearch = useGroupSearch(groupSearchParams, minScore)
```

**Step 3: Add debounce logic for minScore changes in grouped view**

Add this useEffect hook after the existing group search definition (around line 260-270):

```typescript
// Debounce minScore changes in grouped view: raising threshold is instant (filter),
// lowering threshold refetches from page 0 to ensure we have results
useEffect(() => {
  if (viewMode !== 'grouped' || !submittedQuery) return

  const prevScoreRef = useRef(minScore)
  const debounceTimer = useRef<NodeJS.Timeout>()

  // If we're lowering the threshold (more lenient), debounce and refetch
  if (minScore < (prevScoreRef.current ?? minScore)) {
    debounceTimer.current = setTimeout(() => {
      groupSearch.reset() // Reset to page 0
      prevScoreRef.current = minScore
    }, 400)
  } else {
    // Raising threshold (stricter): instant filter via the groups memo in useGroupSearch
    prevScoreRef.current = minScore
  }

  return () => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
  }
}, [minScore, viewMode, submittedQuery, groupSearch])
```

**Note:** You'll need to import `useRef` at the top of the file if not already imported:
```typescript
import { useMemo, useRef, useEffect } from 'react'
```

**Step 4: Verify the changes compile**

Run: `cd frontend && npm run type-check`
Expected: No TypeScript errors

**Step 5: Commit**

```bash
git add frontend/src/hooks/useGallerySearch.ts
git commit -m "feat: pass minScore to useGroupSearch with debounce for threshold changes"
```

---

## Task 3: Implement Edit All image fetching in Gallery component

**Files:**
- Modify: `frontend/src/pages/Gallery.tsx`
- Modify: `frontend/src/hooks/useGalleryDialogs.ts` (add state for seedImages)

**Step 1: Add state for Edit All seedImages and loading in useGalleryDialogs**

In `frontend/src/hooks/useGalleryDialogs.ts`, add these state variables after the existing dialog states (around line 80-85):

```typescript
const [editAllSeedImages, setEditAllSeedImages] = useState<Image[]>([])
const [editAllLoading, setEditAllLoading] = useState(false)
```

And add these to the return object:

```typescript
editAllSeedImages,
setEditAllSeedImages,
editAllLoading,
setEditAllLoading,
```

**Step 2: Update Gallery.tsx to import and use the new states**

In `frontend/src/pages/Gallery.tsx`, update the useGalleryDialogs initialization to destructure the new properties:

```typescript
const dialogs = useGalleryDialogs(search.displayImages)
```

becomes:

```typescript
const {
  showMassEdit,
  setShowMassEdit,
  editAllSeedImages,
  setEditAllSeedImages,
  editAllLoading,
  setEditAllLoading,
  ...restDialogs
} = useGalleryDialogs(search.displayImages)

// For backward compatibility, create dialogs object with remaining properties
const dialogs = {
  showMassEdit,
  setShowMassEdit,
  editAllSeedImages,
  setEditAllSeedImages,
  editAllLoading,
  setEditAllLoading,
  ...restDialogs,
}
```

**Step 3: Add onOpenMassEdit handler that fetches images for grouped view**

In `frontend/src/pages/Gallery.tsx`, add this handler before the return statement (around line 75):

```typescript
const handleOpenMassEdit = async () => {
  // If individual view, just open the dialog with current images
  if (search.viewMode === 'individual') {
    dialogs.setShowMassEdit(true)
    return
  }

  // Grouped view: fetch all matching images with current filters
  if (search.viewMode === 'grouped' && search.totalGroups <= 100) {
    dialogs.setEditAllLoading(true)
    try {
      const response = await searchApi.search({
        query: search.submittedQuery || '',
        ...search.filters,
        image_types: search.imageType === 'all' ? [] : [search.imageType],
        limit: 2000,
        offset: 0,
      })
      dialogs.setEditAllSeedImages(response.results)
      dialogs.setShowMassEdit(true)
    } catch (error) {
      toast.error('Failed to load images for bulk edit')
      console.error(error)
    } finally {
      dialogs.setEditAllLoading(false)
    }
  }
}
```

**Step 4: Update the EditGroupDialog seedImages prop**

Find the EditGroupDialog component in Gallery.tsx (around line 249) and update the seedImages prop:

From:
```typescript
seedImages={search.displayImages}
```

To:
```typescript
seedImages={search.viewMode === 'grouped' ? dialogs.editAllSeedImages : search.displayImages}
```

Also add the loading state to the button in GalleryHeader. In `frontend/src/components/GalleryHeader.tsx`, update the Edit All button around line 368:

```typescript
<button
  onClick={onOpenMassEdit}
  disabled={search.editAllLoading}
  title={search.editAllLoading ? 'Loading images...' : 'Bulk-edit all groups in current results'}
  className="flex items-center gap-1.5 hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
>
  {search.editAllLoading ? (
    <Loader2 className="h-3 w-3 animate-spin" />
  ) : (
    <Pencil className="h-3 w-3" />
  )}
  Edit all ({totalGroups})
</button>
```

**Step 5: Update GalleryHeader props to receive editAllLoading**

In `frontend/src/components/GalleryHeader.tsx`, update the props interface and function signature around line 55-75:

```typescript
export interface GalleryHeaderProps {
  search: UseGallerySearchReturn & {
    editAllLoading?: boolean
  }
  onOpenImport: () => void
  onOpenTagManagement: () => void
  onOpenSystemInfo: () => void
  onOpenMassEdit: () => void
  displayImageCount: number
}
```

And update the Gallery.tsx call to GalleryHeader (around line 80-87):

```typescript
<GalleryHeader
  search={{ ...search, editAllLoading: dialogs.editAllLoading }}
  onOpenImport={() => dialogs.openImportDialog()}
  onOpenTagManagement={() => dialogs.setShowTagManagement(true)}
  onOpenSystemInfo={() => dialogs.setShowSystemInfo(true)}
  onOpenMassEdit={handleOpenMassEdit}
  displayImageCount={search.displayImages.length}
/>
```

**Step 6: Import Loader2 icon if not already imported**

At the top of `frontend/src/components/GalleryHeader.tsx`, verify Loader2 is imported:

```typescript
import { ..., Loader2, ... } from 'lucide-react'
```

**Step 7: Import searchApi if not already imported in Gallery.tsx**

At the top of `frontend/src/pages/Gallery.tsx`, verify this import exists:

```typescript
import { groupApi, searchApi } from '@/lib/api'
```

If only `groupApi` is imported, add `searchApi` to the import.

**Step 8: Verify the changes compile**

Run: `cd frontend && npm run type-check`
Expected: No TypeScript errors

**Step 9: Format and lint the files**

Run: `cd frontend && npx eslint src/pages/Gallery.tsx src/components/GalleryHeader.tsx src/hooks/useGalleryDialogs.ts --fix && npx prettier --write src/pages/Gallery.tsx src/components/GalleryHeader.tsx src/hooks/useGalleryDialogs.ts`
Expected: Files are formatted

**Step 10: Commit**

```bash
git add frontend/src/pages/Gallery.tsx frontend/src/components/GalleryHeader.tsx frontend/src/hooks/useGalleryDialogs.ts
git commit -m "feat: implement Edit All image fetching for grouped view with loading state"
```

---

## Task 4: Run all backend tests to verify nothing broke

**Files:**
- Test: `backend/tests/integration/test_search_endpoint.py` and all other backend tests

**Step 1: Run all backend tests**

Run: `cd /c/Users/jenni/Code/scene-atlas && uv run pytest backend/tests/ -q --tb=short`
Expected: 670+ tests pass (or whatever the current count is)

**Step 2: If any tests fail, investigate and fix**

If failures occur, review the error messages and fix the code accordingly.

**Step 3: Commit if fixes were needed**

```bash
git add [modified files]
git commit -m "fix: [description of fix if needed]"
```

---

## Task 5: Run frontend linting and formatting

**Files:**
- All modified frontend files

**Step 1: Run ESLint on modified files**

Run: `cd frontend && npx eslint src/pages/Gallery.tsx src/components/GalleryHeader.tsx src/hooks/useGallerySearch.ts src/hooks/useGalleryDialogs.ts --max-warnings=0`
Expected: No errors or warnings

**Step 2: Run Prettier check**

Run: `cd frontend && npx prettier --check src/pages/Gallery.tsx src/components/GalleryHeader.tsx src/hooks/useGallerySearch.ts src/hooks/useGalleryDialogs.ts`
Expected: All files are properly formatted

**Step 3: If formatting is needed, auto-fix**

Run: `cd frontend && npx prettier --write src/pages/Gallery.tsx src/components/GalleryHeader.tsx src/hooks/useGallerySearch.ts src/hooks/useGalleryDialogs.ts`

**Step 4: Commit if changes were made**

```bash
git add [files that were formatted]
git commit -m "chore: format frontend code"
```

---

## Task 6: Manual testing checklist

**Test Environment:** Run the app locally and test the following scenarios:

### 6.1 Browse Mode (No Query)
- [ ] Open gallery, switch to grouped view
- [ ] Verify groups display with hero + mosaic images
- [ ] Verify relevance slider is NOT visible (no query)
- [ ] Verify Edit All button is visible and enabled if ≤100 groups
- [ ] Click Edit All, verify dialog opens with grouped images

### 6.2 Search Mode - Relevance Slider Raising (Stricter)
- [ ] Type a query (e.g., "forest")
- [ ] Verify relevance slider appears in header
- [ ] Drag slider to the right (raise threshold, e.g., 50%)
- [ ] Verify groups instantly filter out lower-scoring results
- [ ] Verify no network request is made (instant client-side filter)

### 6.3 Search Mode - Relevance Slider Lowering (Lenient)
- [ ] With slider at 50%, drag it left to 25%
- [ ] Verify after ~400ms debounce, groups refetch from page 0
- [ ] Verify more groups appear (matching the lower threshold)
- [ ] Verify infinite scroll resets (starts at page 0)

### 6.4 Edit All with Grouped View + Filters
- [ ] Search for "dungeon" (or any term that returns groups)
- [ ] Apply a filter (e.g., author filter)
- [ ] Verify Edit All button shows filtered group count
- [ ] Click Edit All, verify dialog loads with all matching images
- [ ] In dialog, verify images are from matched groups

### 6.5 Individual View - Existing Behavior Unchanged
- [ ] Switch to individual view
- [ ] Verify Edit All still works as before (uses displayImages)
- [ ] Verify relevance slider still filters individual images

### 6.6 Infinite Scroll + Slider Interaction
- [ ] In grouped view with query, scroll to bottom to load more groups
- [ ] While loading, adjust slider
- [ ] Verify slider adjustments work correctly during pagination

---

## Task 7: Final commit and summary

**Step 1: Review all changes**

Run: `git log --oneline -5` to see recent commits

**Step 2: Create a summary of changes**

Verify these commits exist:
- `feat: add minScore filtering to useGroupSearch hook`
- `feat: pass minScore to useGroupSearch with debounce for threshold changes`
- `feat: implement Edit All image fetching for grouped view with loading state`

**Step 3: Verify all tests pass one more time**

Run: `uv run pytest backend/tests/ -q && cd frontend && npm run type-check && npx eslint src/ --max-warnings=0`
Expected: All checks pass

---

## Summary

This plan implements:
1. **Relevance slider filtering** - Groups filtered client-side when raising threshold (instant), debounce 400ms when lowering (refetch)
2. **Edit All functionality** - Fetches all matching images when clicked in grouped view (≤100 group limit)
3. **Full testing** - All backend tests pass, frontend linting passes, manual testing of both features

**Total Estimated Time:** ~1.5 hours for implementation + testing
