# Group View: Hero + Mosaic Design

## Overview

An alternative gallery view mode that displays images grouped by image group, using a "Hero + Mosaic" card layout. Toggled via toolbar buttons alongside the existing individual image grid.

## Motivation

Many battlemaps come in 10-50+ scenes (snowy, fey, summer, gridded, etc.). The flat image grid shows each scene as an identical-looking card, making it hard to:
- Discover what map *concepts* exist
- See the variety within a group at a glance
- Find the right scene of a specific map

## Card Layout

```
┌───────────────────────────────────────────┐
│ ┌──────────────┐ ┌─────────┐┌─────────┐  │
│ │              │ │ scene 2 ││ scene 3 │  │
│ │  Hero Image  │ ├─────────┤├─────────┤  │
│ │  (60%)       │ │ scene 4 ││ +18     │  │
│ │              │ │         ││ more    │  │
│ └──────────────┘ └─────────┘└─────────┘  │
├───────────────────────────────────────────┤
│  Dungeon of the Dead Lord  [23 scenes]   │
│  Czepeku       [underground] [dark] [+5] │
└───────────────────────────────────────────┘
```

- **Card size**: ~420px wide, 160px image area + ~40px metadata bar
- **Hero area**: 60% width, shows primary or best-matching scene
- **Mosaic area**: 40% width, CSS grid using **even tile counts only** (1, 2, or 4)
- **Overflow**: Last mosaic tile shows "+N more" overlay when group has more scenes
- **Metadata bar**: Always visible (not hover-only) — name, author, scene count badge, up to 3 tag badges

### Why Even Tile Counts Only

Using only 1, 2, or 4 mosaic tiles eliminates empty grid cells that occur with odd counts in a 2-column layout. If there are 3 remaining scenes, we show 2 + "+N more". If 5+, we show 4 tiles (last one as overflow).

## Search & Filter Behavior

### Filter Search (authors, tags)
- Only scenes matching the filter appear in each group's mosaic
- Group is visible if **any** scene matches
- Badge shows "3/23" (matching/total) when filtered

### Text/Semantic Search
- Groups sorted by **best-matching scene's semantic score** (descending)
- Hero image = highest-scoring scene in the group
- Mosaic prioritises matching scenes over non-matching ones

### No Search (browsing)
- Groups sorted alphabetically by `baseName`
- Hero = first image in group
- Mosaic shows first scenes

## ImageViewer Scene Panel

When viewing a group's image, the sidebar shows scenes **partitioned by subgroup**:

```
Scenes (23)

SNOWY
  [tile] [tile]
  [tile] [tile]

FEY
  [tile] [tile]

SUMMER
  [tile] [tile]
```

- Each unique `subgroup` value becomes a section header
- Tiles show filename (without extension), grid badge, and up to 2 tag badges
- Subgroup name is NOT repeated on tiles since the section header shows it
- Scenes without a `subgroup` go into "Other"
- Single-section groups show no header
- Scene panel scrolls independently; metadata header stays fixed
- Sidebar height matches image container (`max-height: 85vh`)

## Architecture

### Approach: Dedicated Backend Endpoint with Client-Side Grouping

The grouped view uses a two-tier approach:

1. **Backend** (`/api/v1/search/groups`): Returns `GroupSearchResult[]` — pre-grouped results with paginated groups, best-matching image IDs, and full group metadata. Handles pagination at the group level (default 25 groups per page, max 500). Supports filtering by all search parameters (text, tags, authors, colors, semantic) and score thresholds via relevance slider.

2. **Frontend**: A `useGallerySearch` hook manages search/filter state and infinite scroll pagination. Results are rendered directly by `GroupGrid` without needing client-side grouping transformation.

### Data Flow

```
Search API (grouped) → GroupSearchResult[] → useGallerySearch hook → GroupGrid → GroupCard[]
                                                                          ↑
                                         (Full Image[] re-fetched via groupApi.get
                                          when opening edit dialogs)
```

### Why Dedicated Endpoint?

The original design used client-side grouping (fetching flat `Image[]` from `/search` and grouping locally). This approach had limitations when scaling:

1. **Pagination conflict**: Text/semantic search returns images paginated by count (limit: 2000), but groups can contain hundreds of images each. Groups in the middle of a list could be split across pages, breaking the UI.

2. **Edit All truncation**: The "Edit All" feature for mass-editing groups needed to fetch all matching images. With image-level pagination, querying `limit: 2000` would miss groups with >2000 images or silently truncate large result sets.

3. **Score inclusion**: Returning scores for semantic search required calculating semantic similarity for every image, even non-matching ones in large groups — wasteful if only group-level best scores were needed.

**Solution**: Implement group-level pagination and return only in-scope image IDs. This eliminates the truncation risk and makes Edit All reliable regardless of group or result set size.

### Query Modes

#### Browse Mode (no query)
- Groups sorted alphabetically
- Returns all groups with their full image ID lists
- Used for initial "all groups" view

#### Search Mode (text or semantic query)
- Groups sorted by best-matching image score (descending)
- Returns only matching image IDs for each group (non-matching group members excluded)
- Used when user enters a search query or applies relevance slider
- `all_image_ids` field contains in-scope images for Edit All (marked as `outOfScope` if not in query results)

### Key Types

```typescript
type ViewMode = 'individual' | 'grouped'

// Backend response (from /api/v1/search/groups)
interface GroupSearchResult {
  groupId: number
  baseName: string
  author: string | null
  totalScenes: number          // total images in group
  matchingCount: number        // matching current search/filter (may be < totalScenes in search mode)
  bestScore: number | null     // highest semantic score (for sorting)
  allImageIds?: number[]       // in-scope image IDs (populated when include_all_image_ids=true)
}

interface GroupSearchResponse {
  groups: GroupSearchResult[]
  totalGroups: number          // total matching groups (across all pages)
  page: number
  limit: number
}

// Frontend rendering (after fetching images via groupApi.get)
interface ImageGroup {
  groupId: number
  baseName: string
  author: string
  heroImage: Image             // primary/best-matching scene
  mosaicImages: Image[]        // up to 4 scenes for the mosaic
  totalScenes: number
  matchingCount: number
  bestScore: number | null
  aggregatedTags: Tag[]        // union of tags across matching scenes
}

// Minimal reference used for Edit All seeding
type SeedImage = { id: number; group_id: number | null }
```

### Files

**Backend:**
| File | Purpose |
|------|---------|
| `backend/app/api/search.py` | `/search/groups` endpoint with browse/search modes, score calculation, image ID collection |
| `backend/app/models/schemas.py` | `GroupSearchResult`, `GroupSearchResponse`, `SeedImage` types |

**Frontend - Search & State:**
| File | Purpose |
|------|---------|
| `frontend/src/hooks/useGallerySearch.ts` | Infinite scroll pagination, filter/search state, `groupSearchParams` export |
| `frontend/src/lib/api/searchApi.ts` | `groups()` function with `include_all_image_ids` parameter |
| `frontend/src/types/index.ts` | `GroupSearchResult`, `GroupSearchResponse`, `SeedImage`, `SearchParams` |

**Frontend - Rendering:**
| File | Purpose |
|------|---------|
| `frontend/src/components/GroupCard.tsx` | Hero + Mosaic card component (unchanged) |
| `frontend/src/components/GroupGrid.tsx` | Virtualized grid of GroupCards with infinite scroll |
| `frontend/src/components/GalleryHeader.tsx` | Edit All button with group count threshold (≤500) |

**Frontend - Edit All & Dialog:**
| File | Purpose |
|------|---------|
| `frontend/src/pages/Gallery.tsx` | `handleOpenMassEdit` fetches groups with image IDs, seeds dialog |
| `frontend/src/hooks/useGalleryDialogs.ts` | `editAllSeedImages: SeedImage[]` state |
| `frontend/src/hooks/useEditGroupLoad.ts` | Accepts `SeedImage[]`, marks non-seeded images as `outOfScope` |
| `frontend/src/components/EditGroupDialog.tsx` | `seedImages?: SeedImage[]` prop |

**Frontend - Image Viewing:**
| File | Purpose |
|------|---------|
| `frontend/src/components/ImageViewer.tsx` | Scene clicking, subgroup sections, sidebar layout |

### Visual Consistency

All card components follow the shared visual language documented in [visual-language.md](visual-language.md): always-visible metadata bars, consistent hover treatment, outline tag badges, and matching border/shadow patterns.

## Known Limitations & Future Enhancements

**Current limitations:**
- Edit All is disabled when >500 groups are present (backend max pagination limit)
- Relevance slider only appears in search mode (requires semantic scores)

**Future enhancements:**
- Expand/collapse group cards inline to see all scenes without opening ImageViewer
- Group-level bulk tagging (tag all scenes in a group at once)
- `description` field on ImageGroup for user-added notes
- Cache pre-computed group thumbnails to avoid repeated image fetches
- Smart mosaic image selection (prefer varied subgroups over all same subgroup)
