# Search Performance & Groups Endpoint Design

**Date:** 2026-03-03

## Context

With ~5,000 scenes, the gallery grouped view shows too few group cards because it fetches 500 individual scenes then groups client-side. Large groups consume disproportionate slots (a group with 30 variants uses 30/500 budget but produces 1 card). The target dataset is 100,000 scenes, and the current search is already getting slow due to N+1 query issues and missing optimizations.

**Solution:** Two-phase approach — fix search performance first, then build a dedicated groups endpoint with group-level pagination.

## Problem Analysis

### Current Flow
1. Frontend requests `GET /api/v1/search/?limit=500` (hardcoded in `useGallerySearch.ts:186`)
2. Backend returns up to 500 individual `ImageResponse` objects
3. Frontend's `useImageGrouping` hook groups them by `group_id` client-side
4. Result: if groups average 10 images, only ~50 group cards displayed

### Performance Bottlenecks Found
1. **N+1 queries**: No eager loading in search endpoint. Pydantic `from_attributes=True` triggers lazy-loads for tags, colors, group, and group.images on every image (~2000 extra queries for 500 results)
2. **`group_image_count` property**: Calls `len(self.group.images)` loading all group members just to count them
3. **No CLIP text cache**: Every search re-encodes query text via ONNX (~100-200ms)
4. **Qdrant RLock**: All vector operations serialized through threading.RLock despite Qdrant being thread-safe
5. **Missing indexes**: No indexes on `tags.image_id`, `colors.image_id`, `images.variant_group_id`, `images.gridded`, `images.grid_type`, `images.image_type`, `images.media_type`

## Design Decisions

- **Approach chosen**: Dedicated groups endpoint (vs. collapse mode on existing endpoint or two-phase client fetch)
- **Rationale**: Group view needs fundamentally different query semantics (paginate by group, not image)
- **group_image_count**: Stored column on `variant_groups` (vs. subquery load or hybrid property)
- **Rationale**: Avoids loading all group images; slight write overhead on import is acceptable
- **Vector quantization**: Skipped for now (user decision)
- **Search in grouped view**: Hero = best match, mosaic = next-best matches then non-matches

## Phase 1: Search Performance Fixes

See implementation plan for details. Fixes: eager loading, stored image_count, CLIP cache, RLock removal, database indexes.

## Phase 2: Groups Endpoint

`GET /api/v1/search/groups` with group-level pagination (default 50 groups/page). Same filter params as existing search. Returns `GroupResult[]` with hero_image, mosaic_images, total_scenes, matching_scenes, best_score, aggregated_tags.

### Search Behavior
- Browsing: query variant_groups directly, paginate at group level
- Search: run hybrid search with larger candidate pool, collapse by group, rank by best score
- Hero selection: best-scoring match (search) or primary_image (browsing)
- Mosaic filling: next-best matches, then non-matching images from group
