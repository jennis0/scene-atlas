# Search Groups Endpoint — Implementation Handover

**Date:** 2026-03-06
**Status:** ~75% complete — backend functional, frontend infrastructure in place
**Branch:** `main` (all work in progress)

---

## Summary of Completed Work

This handover covers Phase 3 of the grouped view overhaul: a server-side `/api/v1/search/groups` endpoint with infinite scroll on the frontend.

### What Has Been Done ✅

#### Backend (Complete & Functional)

1. **Schema Refactoring** ✅
   - Renamed `GroupSearchItem` → `GroupPickerItem` and `GroupSearchResponse` → `GroupPickerResponse` across:
     - `backend/app/models/schemas.py` (definition)
     - `backend/app/api/groups.py` (route return type, instance creation)
     - `frontend/src/types/index.ts` (TypeScript equivalents)
     - `frontend/src/lib/api/groupApi.ts` (import)
     - `frontend/src/components/MergeGroupPicker.tsx` (import + prop type)
     - `frontend/src/hooks/useEditGroupOperations.ts` (import + parameter type)
   - **Why:** The existing `GroupSearchItem/Response` are for the merge picker dialog (`/groups/search`). The new endpoint needs `GroupSearchResult/GroupSearchResponse` to avoid name collisions.

2. **New Schemas** ✅
   - Added to `backend/app/models/schemas.py` (lines 170–191):
     ```python
     class GroupSearchResult(BaseModel)
     class GroupSearchResponse(BaseModel)
     ```
   - Added to `frontend/src/types/index.ts` (after `GroupPickerResponse`):
     ```typescript
     export interface GroupSearchResult
     export interface GroupSearchResponse
     ```

3. **Filter Helper Extraction** ✅
   - **File:** `backend/app/api/search.py`
   - **Function:** `_build_image_filter_query(db, image_types, media_types, ...) -> Query`
   - **Lines:** Added at top of file, before `search_images()` endpoint
   - **Purpose:** Reusable filter-building logic for both image search and group search
   - **Details:** Extracted inline lines 158–222 from original `search_images`, handles all filter conditions: image_types, media_types, gridded, grid_type, authors, exclude_authors, tags, exclude_tags, colors

4. **New `/api/v1/search/groups` Endpoint** ✅
   - **File:** `backend/app/api/search.py` (lines 387–527)
   - **Route:** `GET /groups` on the search router
   - **Parameters:** Same as image search (query, filters, sort_by, sort_dir) + limit (default 50, max 500), offset
   - **Two Modes:**

     **Browse Mode** (no query):
     - Returns all groups sorted by `sort_by`/`sort_dir` (supports `created_at`, `name`)
     - Loads primary image for each group as `hero_image`
     - `mosaic_images = []`, `best_score = None` (no query = no relevance)
     - `matching_scenes = total_scenes` (all scenes match by default)

     **Search Mode** (query present):
     - Runs hybrid FTS5 + CLIP search with candidate pool `max(limit*20, 1000)`
     - Collapses results by `group_id` in Python, keeping all per-image scores
     - Sorts groups by `max(score)` DESC
     - Hero = highest-scoring image in group
     - Mosaic = up to 4 next-best images, filled with additional group members if needed (batch query to avoid N+1)
     - Returns RRF-normalized [0,1] scores
     - `total_groups` reflects found groups (may be lower bound on very large diverse libraries)

   - **Key Implementation Details:**
     - RRF (Reciprocal Rank Fusion) with K=60, text weight=1.1, alias weight=0.5
     - Mosaic fill via single batch query: `WHERE variant_group_id IN (...) AND id NOT IN (already_selected)`
     - Both hero and mosaic images loaded with `subqueryload(Image.tags)` and `subqueryload(Image.colors)`

5. **Increased Image Search Limit** ✅
   - Changed `limit` constraint in `search_images()` from `le=1000` to `le=2000`
   - **Purpose:** Edit All in grouped view may need to fetch more images (up to 1000 limit → all matching images when enabled)

#### Frontend (Infrastructure Complete)

6. **Frontend Types** ✅
   - **File:** `frontend/src/types/index.ts`
   - Added `GroupSearchResult` and `GroupSearchResponse` interfaces after `GroupPickerResponse`
   - All fields match backend schema

7. **API Client Method** ✅
   - **File:** `frontend/src/lib/api/searchApi.ts`
   - Added `groups()` method: `async (params: SearchParams & { limit?; offset? }): Promise<GroupSearchResponse>`
   - Calls `GET /api/v1/search/groups` with params

8. **Query Keys** ✅
   - **File:** `frontend/src/lib/queryKeys.ts`
   - Added `groups: ['groups'] as const` to `QUERY_KEYS`
   - Allows prefix-based cache invalidation

9. **useGroupSearch Hook** ✅
   - **File:** `frontend/src/hooks/useGroupSearch.ts` (new)
   - Uses React Query `useInfiniteQuery` with `PAGE_SIZE=50`
   - Maps `GroupSearchResult[]` → `ImageGroup[]` for existing `GroupCard` component
   - Synthesises `aggregatedTags` from hero + mosaic images (partial coverage, same dedup logic as `useImageGrouping`)
   - Returns: `{ ...query, groups, totalGroups }`
   - Ready for infinite scroll integration

---

## What Remains (~25%)

### 1. Backend Tests (High Priority)

**File:** `backend/tests/integration/test_search_endpoint.py`

Need to add a new `TestGroupsEndpoint` test class with:
- **Fixture:** Seed 2-3 `ImageGroup` rows (3+ images each) to test mosaic fill
- **Browse mode tests:**
  - Groups returned sorted by `created_at DESC` (default)
  - Groups sorted alphabetically by `name` when `sort_by=name`
  - `total_groups` = correct group count
  - `offset=1` skips first group correctly
  - `mosaic_images` is empty in browse mode
- **Search mode tests:**
  - Groups sorted by `best_score DESC`
  - Hero = highest-scoring image in group
  - `matching_scenes` = count of matched images per group
  - Mosaic filled with non-matching group members when <4 score-ranked matches (verifies batch fill)
  - Filters (author, tags, gridded) applied before grouping
  - RRF scoring produces [0,1] normalized scores

**Estimated effort:** 1–2 hours

### 2. Gallery Integration (Medium-High Priority)

**Files to modify:**
- `frontend/src/pages/Gallery.tsx`
- `frontend/src/components/GalleryHeader.tsx`
- `frontend/src/hooks/useGallerySearch.ts`

**What's needed:**
1. **Branch on viewMode in gallery component:**
   - When `viewMode === 'grouped'`, render infinite scroll grid with sentinel element
   - Use `useGroupSearch` instead of `useImageGrouping`
   - Flatten `data.pages` → `ImageGroup[]` (done in hook)

2. **Infinite scroll UI:**
   - Add `<div ref={sentinelRef} />` at bottom of group grid
   - Attach `IntersectionObserver` with `rootMargin: '200px'` for pre-fetching
   - Show loading spinner on sentinel while `isFetchingNextPage`
   - Show "All N groups loaded" text when `!hasNextPage`

3. **Result count display:**
   - Update `GalleryHeader` to show `totalGroups` when in grouped view
   - Display as e.g. "87 groups" or "Showing 50 of 87 groups"

4. **Filter/sort integration:**
   - Pass `sort_by`, `sort_dir`, and all filter params from gallery state to `useGroupSearch`
   - When filters change, React Query automatically refetches from page 0

**Estimated effort:** 2–3 hours

### 3. Relevance Slider in Grouped View (Low-Medium Priority)

**Files to modify:**
- `frontend/src/hooks/useGroupSearch.ts`
- `frontend/src/hooks/useGallerySearch.ts`
- Gallery component

**Implementation:**
- Add `minScore` param to `useGroupSearch`
- **Raising slider** (stricter threshold): Filter loaded groups client-side instantly — `groups.filter(g => g.bestScore === null || g.bestScore >= minScore)`
- **Lowering slider** (more lenient): Debounce 400ms, then change query key to refetch from page 0
- In browse mode, slider is hidden (no scores available)

**Estimated effort:** 1–2 hours

### 4. Edit All in Grouped View (Medium Priority)

**Files to modify:**
- `frontend/src/pages/Gallery.tsx`
- `frontend/src/components/GalleryHeader.tsx`

**Implementation:**
1. When `viewMode === 'grouped'` and Edit All is clicked:
   - Check `totalGroups` from hook
   - **If > 100 groups:** Disable button, show tooltip `"Too many groups (N) — apply filters to narrow below 100"`
   - **If ≤ 100 groups:** Fetch `/api/v1/search` with all current filters + `limit=2000` to get complete flat image list

2. Pass fetched images as `seedImages` to `EditGroupDialog` (existing component)

3. UI: Show loading state on button during fetch; disabled state with tooltip when over threshold

**Note:** The existing `useEditGroupLoad` hook already calls `groupApi.get(id)` per group to load full group detail. No changes needed there.

**Estimated effort:** 1–2 hours

### 5. Testing & Verification (Low Priority)

- Run `uv run pytest backend/tests/ -q` — all tests should pass (670+)
- Run backend linting: `uv run ruff format backend/ && uv run ruff check backend/`
- Run frontend linting: `cd frontend && npx eslint src/ && npx prettier --check src/`
- Manual testing:
  - Browse mode: switch to grouped view, verify groups load and sort correctly
  - Search mode: type a query, verify groups load, scroll to bottom
  - Relevance slider: adjust in grouped view, verify behavior
  - Edit All: try with different group counts, test threshold
  - Filters: apply filters, verify groups update

**Estimated effort:** 1–2 hours

---

## Critical Notes for Next Phase

### Architecture

1. **Every image belongs to a group.** No ungrouped image handling anywhere in the app. `variant_group_id IS NULL` should not occur in normal operation.

2. **`image_count` is trigger-maintained.** Don't compute it via SQL; it's kept current by SQLite triggers on image INSERT/DELETE/UPDATE. Safe to query directly on `ImageGroup.image_count`.

3. **Mosaic fill is batch-queried.** After taking hero + top 4 scored images per group, for groups with <5 mosaic candidates, fetch additional members with one query per page: `WHERE group_id IN (...) AND id NOT IN (already_selected)`.

4. **RRF scores are normalized to [0,1].** The frontend relevance slider expects this range; don't skip the normalization step.

5. **`total_groups` in search mode is an approximation** based on the candidate pool (limit*20). On very large diverse libraries, this may undercount. The UI should not present it as a guaranteed total — it's "groups found in search results."

### Git & Branches

- All changes on `main` branch; no worktrees needed
- Schema changes are backward-compatible (new schemas added, old ones renamed but structure unchanged)
- Database schema unchanged (no migrations needed)

### Related Files & Dependencies

- **FTS5 service:** `backend/app/services/fts_service.py` (fts_search, fts_search_terms, get_alias_expansions)
- **CLIP service:** `backend/app/services/__init__.py` (get_clip_service)
- **Qdrant service:** `backend/app/services/__init__.py` (get_qdrant_service)
- **Color search:** `backend/app/services/color_search.py` (color_index)
- **Frontend:** Existing `GroupCard.tsx`, `useImageGrouping.ts` (can serve as reference for client-side grouping logic)

### Known Limitations & Tradeoffs

1. **Mosaic fill uses any group member**, not just matched members. This provides visual variety but may surprise users if a non-matching image appears in the mosaic. Document in release notes if needed.

2. **Infinite scroll doesn't pre-materialize all groups.** Only the loaded page's images are in memory. Edit All threshold (100 groups) prevents attempting to edit too many groups at once.

3. **Relevance slider in grouped view uses mixed client/server logic.** Raising threshold is instant (client-side filter); lowering threshold refetches from server (debounced). This is an acceptable UX tradeoff to avoid excessive network traffic.

---

## Files Modified Summary

### Backend
- `backend/app/models/schemas.py` — renamed picker schemas, added `GroupSearchResult/Response`
- `backend/app/models/__init__.py` (imports) — if `ImageGroup` not already exported, add it
- `backend/app/api/search.py` — added `_build_image_filter_query()` helper, added `/groups` endpoint, raised limit to 2000
- `backend/app/api/groups.py` — updated imports & route return type (rename)
- `backend/tests/integration/test_search_endpoint.py` — **TO DO:** add `TestGroupsEndpoint`

### Frontend
- `frontend/src/types/index.ts` — renamed picker types, added group search types
- `frontend/src/lib/api/searchApi.ts` — added `groups()` method
- `frontend/src/lib/queryKeys.ts` — added `groups` key
- `frontend/src/lib/api/groupApi.ts` — updated import (rename only)
- `frontend/src/components/MergeGroupPicker.tsx` — updated import (rename only)
- `frontend/src/hooks/useEditGroupOperations.ts` — updated import (rename only)
- `frontend/src/hooks/useGroupSearch.ts` — **DONE:** new hook
- `frontend/src/pages/Gallery.tsx` — **TO DO:** add infinite scroll integration
- `frontend/src/components/GalleryHeader.tsx` — **TO DO:** branch on viewMode for result count & Edit All
- `frontend/src/hooks/useGallerySearch.ts` — **TO DO:** branch on viewMode, relay params

---

## How to Continue

1. **Start with backend tests** (highest confidence, unblocks verification)
2. **Then gallery integration** (core UX, most user-facing)
3. **Then relevance slider & Edit All** (polish & feature completeness)
4. **Finally, test & verify** (full end-to-end)

All code is committed to `main` and ready for the next phase. No worktrees or branch management needed.

Good luck! 🚀
