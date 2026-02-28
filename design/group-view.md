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

### Approach: Client-Side Grouping

The existing search endpoint returns flat `Image[]` with `group_id` on each image. Rather than duplicating search logic in a new grouped endpoint:

1. **Backend**: Added `scores` field to `ImageSearchResponse` — a `Dict[int, float]` mapping image_id to semantic similarity score (only populated on semantic search)
2. **Frontend**: A `useImageGrouping` hook transforms flat `Image[]` into `ImageGroup[]` client-side

### Data Flow

```
Search API → Image[] + scores? → useImageGrouping hook → ImageGroup[] → GroupGrid → GroupCard[]
                                       ↑
                               allImages (for true group scene counts)
```

### Key Types

```typescript
type ViewMode = 'individual' | 'grouped'

interface ImageGroup {
  groupId: number | null       // group_id, null for ungrouped
  baseName: string             // group display name
  author: string
  heroImage: Image             // primary/best-matching scene
  mosaicImages: Image[]        // up to 4 scenes for the mosaic
  totalScenes: number          // true group size (from allImages cross-ref)
  matchingCount: number        // count matching current search/filter
  bestScore: number | null     // highest semantic score (for sort)
  aggregatedTags: Tag[]        // union of tags across matching scenes
}
```

### Files

| File | Purpose |
|------|---------|
| `frontend/src/hooks/useImageGrouping.ts` | Transforms Image[] → ImageGroup[] |
| `frontend/src/components/GroupCard.tsx` | Hero + Mosaic card component |
| `frontend/src/components/GroupGrid.tsx` | Virtualized grid of GroupCards |
| `backend/app/models/schemas.py` | `scores` field on `ImageSearchResponse` |
| `backend/app/api/search.py` | Captures and passes through qdrant scores |
| `frontend/src/types/index.ts` | `ViewMode`, `ImageGroup`, updated `SearchResult` |
| `frontend/src/pages/Gallery.tsx` | View mode toggle, conditional rendering |
| `frontend/src/components/ImageViewer.tsx` | Scene clicking, subgroup sections, sidebar layout |

### Visual Consistency

All card components follow the shared visual language documented in [visual-language.md](visual-language.md): always-visible metadata bars, consistent hover treatment, outline tag badges, and matching border/shadow patterns.

## Future Enhancements

- Dedicated backend endpoint for grouped search (if client-side grouping becomes a bottleneck)
- Expand/collapse group cards inline to see all scenes without opening ImageViewer
- Group-level bulk tagging (tag all scenes in a group at once)
- `description` field on ImageGroup for user-added notes
