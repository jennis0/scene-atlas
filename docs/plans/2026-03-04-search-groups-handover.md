# Search & Groups — Handover

**Date:** 2026-03-04
**Branch:** `main` (all work merged)
**Tests:** 670 passing

---

## What Has Been Done

The search performance and quality work is **complete and merged to main**. Two migrations need
running on the live DB before deploying: `014_search_performance` and `015_search_ranking`.

### Phase 1 — Performance (migration 014)

| Fix | Files | Detail |
|-----|-------|--------|
| Eager loading | `backend/app/api/search.py` | `subqueryload(tags)`, `subqueryload(colors)`, `joinedload(group)` on base query — eliminates N+1 on all search and browse paths |
| Stored `image_count` | `backend/app/models/database.py`, migration 014 | `variant_groups.image_count` maintained by 3 DB triggers (INSERT/DELETE/UPDATE on `images.variant_group_id`) |
| CLIP text cache | `backend/app/services/clip_service.py` | Module-level 256-entry LRU dict, avoids 100-200ms ONNX inference on repeated queries |
| Qdrant read-lock | `backend/app/services/qdrant_service.py` | Removed `RLock` from read-only methods (`search_similar`, `get_embedding`, `get_collection_info`) |
| DB indexes | migration 014 | `ix_tags_image_id`, `ix_colors_image_id`, `ix_images_variant_group_id`, `ix_images_gridded`, `ix_images_grid_type`, `ix_images_image_type`, `ix_images_media_type` |

### Phase 2 — Search Quality (migration 015)

| Fix | Files | Detail |
|-----|-------|--------|
| RRF ranking | `backend/app/api/search.py` | Reciprocal Rank Fusion (`k=60`) over 3 ranked lists: CLIP semantic, FTS5 text (AND+OR), alias expansion. Replaces fragile `sem + 0.15*txt` formula. |
| FTS5 column weights | `backend/app/services/fts_service.py` | `bm25(image_fts, 10.0, 1.0, 0.5, 5.0)` — name×10, search_text×5, filename×1, author×0.5 |
| Multi-word OR fallback | `fts_service.py:fts_search()` | AND query + OR fallback; OR-only results appended and ranked lower by RRF |
| Alias expansion | `fts_service.py`, `search.py` | Separate FTS5 OR pass for synonyms (e.g. "rainy"→"rain") as third RRF list; avoids BM25 dilution |
| FTS5 candidate pool | `search.py` | Increased from `limit×3` to `limit×10` |
| Tag sync | `backend/app/api/tags.py`, `groups.py` | `rebuild_search_text(image, db)` called after every tag add/remove/rename/bulk-delete so FTS5 stays in sync |
| Alias cache invalidation | `tags.py` | `invalidate_alias_cache()` called after vocab changes |
| Diacritics | migration 015 | Recreates `image_fts` with `tokenize='porter unicode61 remove_diacritics 2'` — Čepeku matches Cepeku |

### Key Architecture Decisions

- **RRF not linear merge**: BM25 scores are scale-free; rank-based fusion avoids normalization fragility.
- **Alias expansion as separate RRF list**: If aliases were OR'd into the main FTS query, images with many tags would get artifically higher BM25 scores (more OR terms matching). Keeping it separate means alias matches get independent RRF contribution.
- **`fts_search_terms()` not `fts_search()` for alias OR**: `fts_search()` passes input through `_sanitize_fts_query()` which strips `OR` operators. Alias expansion uses `fts_search_terms(db, list_of_terms)` which sanitizes each term individually then joins with OR.
- **`db.expire_all()` after bulk tag ops**: `synchronize_session=False` bulk SQL operations leave stale Tag objects in the session identity map. Expiring before reloading ensures `rebuild_search_text` reads fresh tag data.

---

## What Remains: Phase 3 — Group Cards Endpoint

This is the **original trigger** for this work. The gallery grouped view shows too few group cards because 500 individual images are fetched and grouped client-side. Large groups eat disproportionate budget (a 30-variant group uses 30/500 but produces 1 card).

### Problem

- `frontend/src/hooks/useGallerySearch.ts:186` fetches `limit: 500` then passes to `useImageGrouping`
- `frontend/src/hooks/useImageGrouping.ts` groups by `group_id` client-side
- At ~5000 maps, only ~50–100 groups visible in grouped view

### Agreed Design (from `docs/plans/2026-03-03-search-performance-and-groups-design.md`)

**New endpoint:** `GET /api/v1/search/groups`

Same filter params as existing search. Returns **group-level** results with group-level pagination (default 50 groups/page).

**Response shape:**
```python
class GroupSearchResult(BaseModel):
    group_id: int | None           # None = ungrouped image
    base_name: str
    author: str | None
    hero_image: ImageResponse      # best match or primary_image
    mosaic_images: list[ImageResponse]  # next-best, up to 5
    total_scenes: int              # group_image_count (stored column)
    matching_scenes: int           # how many in group matched query
    best_score: float              # highest merged_score in group
    aggregated_tags: dict[str, list[str]]  # category -> [values] for hero

class GroupSearchResponse(BaseModel):
    total_groups: int
    limit: int
    offset: int
    groups: list[GroupSearchResult]
```

**Browsing mode (no query):**
1. Query `variant_groups` directly with `GROUP BY` or `DISTINCT ON group_id`
2. Fetch group records with `image_count` (already stored)
3. Fetch primary image for each group (already stored as `primary_image_id`)
4. Handle ungrouped images as pseudo-groups with `group_id = None`
5. Sort by `created_at DESC` or `name ASC`

**Search mode (query present):**
1. Run hybrid search (same FTS5 + CLIP RRF as existing endpoint) with larger candidate pool (`limit * 20`)
2. Collapse results by `group_id` in Python, keeping all per-image scores
3. Sort groups by `max(merged_score)` across all members
4. Hero = highest-scoring image in group; mosaic = next 5 by score, then non-matching from group
5. For ungrouped images, treat each as its own group

**Pagination:**
- Offset/limit apply to groups, not images
- `total_groups` = distinct group count after filters

### Frontend Changes

**New hook:** `useGroupSearch.ts` (or extend `useGallerySearch.ts`)
- Query `GET /api/v1/search/groups` instead of current `GET /api/v1/search/`
- Same filter params
- No need for `useImageGrouping` — server does the collapsing

**GroupCard component** (`frontend/src/components/GroupCard.tsx`) should already work since it receives `heroImage`, `mosaicImages`, `baseName`, etc. — these map directly to the new response shape.

**Pagination:** Add page controls to the grouped view. Each page = 50 groups.

### Implementation Notes

1. **Reuse existing filter-building code** from `search_images()` — extract the `sql_query` filter assembly into a shared helper, call it from both endpoints.

2. **Ungrouped images**: In browsing, run a second query for `images WHERE variant_group_id IS NULL`. In search, images with `group_id = None` are treated as their own group in the collapse step.

3. **Mosaic filling**: After taking the top-scoring matches for hero and mosaic, fill remaining mosaic slots (up to 5 total) with non-matching images from the same group. These require an extra query per group _or_ fetching all group members upfront. Prefer fetching members lazily only if needed (most groups will have enough matches at `limit * 20` pool).

4. **primary_image_id on ImageGroup**: Already stored (see `database.py`). Use it as fallback hero when browsing without a query.

5. **`image_count` column**: Already stored and maintained by triggers. Use for `total_scenes`.

### Files to Create/Modify

| File | Change |
|------|--------|
| `backend/app/api/search.py` | Add `GET /groups` endpoint; extract shared filter-building helper |
| `backend/app/models/schemas.py` | Add `GroupSearchResult`, `GroupSearchResponse` Pydantic models |
| `frontend/src/hooks/useGallerySearch.ts` | Branch on view mode: call groups endpoint in grouped view |
| `frontend/src/lib/api.ts` | Add `searchApi.groups(params)` method |
| `frontend/src/types/index.ts` | Add `GroupSearchResult`, `GroupSearchResponse` types |
| `backend/tests/integration/test_search_endpoint.py` | Add tests for groups endpoint |

### Tests to Write (Backend)

- Browsing: returns groups sorted by `created_at DESC`, ungrouped images included
- Browsing: `total_groups` count is correct
- Search: groups sorted by `best_score DESC`
- Search: hero is highest-scoring image in group
- Search: mosaic filled with non-matching images when fewer than 5 matches
- Filters (author, tags, gridded) applied before grouping
- Pagination: `offset=50` skips first 50 groups

---

## How to Continue

```bash
# Start a new worktree for Phase 3
# (use superpowers:using-git-worktrees skill)

# Baseline tests
cd /home/joe/scene-atlas
uv run pytest backend/tests/ -q
# Expected: 670 passed
```

**Suggested branch name:** `feature/search-groups-endpoint`

**Start here:** `backend/app/api/search.py` — add the `/groups` route after the existing `/` route. The filter-building block (lines ~174–237) can be extracted into `_build_image_filter_query(db, **filter_params)` and called from both endpoints.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `backend/app/api/search.py` | Main search endpoint + RRF merge logic |
| `backend/app/services/fts_service.py` | FTS5 helpers: `fts_search()`, `fts_search_terms()`, `get_alias_expansions()`, `rebuild_search_text()` |
| `backend/app/models/database.py` | `ImageGroup.image_count` stored column |
| `backend/alembic/versions/014_search_performance.py` | image_count + triggers + indexes |
| `backend/alembic/versions/015_search_ranking.py` | FTS5 tokenizer with diacritics |
| `frontend/src/hooks/useGallerySearch.ts` | Search orchestration + `limit: 500` (change this) |
| `frontend/src/hooks/useImageGrouping.ts` | Client-side grouping (will be replaced by server grouping) |
| `frontend/src/components/GroupCard.tsx` | Group card UI (should not need changes) |
| `docs/plans/2026-03-03-search-performance-and-groups-design.md` | Original design doc |
