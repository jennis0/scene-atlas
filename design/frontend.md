# Frontend Architecture

## Overview

A React single-page application for browsing, searching, and importing battlemap images. Built with TypeScript, Vite, Tailwind CSS, and Radix UI.

See also:
- [visual-language.md](visual-language.md) — shared styling patterns across all card components
- [variant-group-view.md](variant-group-view.md) — grouped view design and architecture

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite (dev server at :5173, proxies `/api` → :8000) |
| Styling | Tailwind CSS |
| UI Primitives | Radix UI (Dialog, Sheet, Checkbox, DropdownMenu) |
| Server State | React Query (`@tanstack/react-query`) |
| Virtualisation | `@tanstack/react-virtual` (row-based virtualisation) |
| HTTP Client | axios |

## Directory Structure

```
frontend/src/
├── components/
│   ├── ui/               # Reusable primitives (button, input, dialog, sheet, badge, etc.)
│   ├── ImageGrid.tsx     # Virtualized individual image grid (200px cards)
│   ├── GroupGrid.tsx     # Virtualized variant group grid (420px hero+mosaic cards)
│   ├── GroupCard.tsx     # Hero + Mosaic card for a variant group
│   ├── ImageViewer.tsx   # Full-screen viewer with variant sections + switching
│   ├── ImportDialog.tsx  # Web import flow (upload, preview, confirm)
│   └── SearchBar.tsx     # Search input component
├── hooks/
│   └── useImageGrouping.ts  # Transforms flat Image[] → ImageGroup[]
├── lib/
│   ├── api.ts            # Axios instance + all API functions
│   └── utils.ts          # Tailwind cn() helper
├── pages/
│   ├── Gallery.tsx       # Main page: search, filters, grid/group toggle, import
│   └── Search.tsx        # Dedicated semantic search page
├── types/
│   └── index.ts          # TypeScript interfaces matching backend schemas
├── App.tsx               # Router setup
└── main.tsx              # Entry point
```

## Key Components

### Gallery (`pages/Gallery.tsx`)
The main page. Contains:
- **Search bar** — text search with toggle between text/semantic mode
- **View mode toggle** — switches between Individual (flat grid) and Grouped (hero+mosaic) views
- **Filter panel** (Sheet/sidebar) — author checkboxes, tag checkboxes grouped by category, color filters. Filter search input to narrow long lists.
- **Import button** — opens ImportDialog
- **Image grid or group grid** — renders filtered/searched images in selected view mode
- **Image viewer** — modal for full-screen viewing with variant switching

**State management:** All filter/search state is local `useState`. Image data fetched via React Query. View mode state controls which grid component renders. The `useImageGrouping` hook transforms flat results into groups client-side.

### ImportDialog (`components/ImportDialog.tsx`)
Three-state dialog for the web import flow:

1. **Upload** — file picker (files or folder via `webkitdirectory`) + zip support. Uploads to `/imports/upload`, gets back grouped variant info.
2. **Preview** — tabbed view (one tab per detected variant group). Each tab: editable author + group name fields, file list with detected tags/grid badges. "Import This Group" or "Import All" buttons.
3. **Processing/Done** — progress per group, completion summary.

State is preserved if dialog is closed during processing (re-open to check progress). An `onActiveChange` callback notifies the Gallery to show a pulsing indicator on the Import button.

### ImageGrid (`components/ImageGrid.tsx`)
Virtualized grid of individual image cards (200px wide, square thumbnails). Each card has an always-visible metadata bar showing name, author, and up to 3 tag badges.

### GroupGrid + GroupCard (`components/GroupGrid.tsx`, `GroupCard.tsx`)
Virtualized grid of variant group cards (420px wide). Each card shows a hero image (60% width) + mosaic of variant thumbnails (40% width) with an always-visible metadata bar. See [variant-group-view.md](variant-group-view.md).

### ImageViewer (`components/ImageViewer.tsx`)
Full-screen overlay for viewing an image at full resolution. Sidebar shows:
- **Fixed metadata header**: name, author, sub-variant badge, grid badge, filename, tags, dominant colors, dimensions
- **Scrollable variant panel**: variants partitioned by `sub_variant` into labelled sections, each with clickable tiles that switch the viewed image

### useImageGrouping (`hooks/useImageGrouping.ts`)
React hook that transforms a flat `Image[]` into `ImageGroup[]`. Handles bucketing by `variant_group_id`, hero selection (score-based for semantic search, positional otherwise), mosaic image selection, tag aggregation, and cross-referencing `allImages` for true group counts.

## API Client (`lib/api.ts`)

Axios instance with:
- Base URL: `/api/v1` (proxied by Vite in dev)
- `paramsSerializer: { indexes: null }` for FastAPI array parameter compatibility (sends `tags=a&tags=b` instead of `tags[0]=a&tags[1]=b`)

Key API groups:
- `imageApi` — list, get, delete, getVariants
- `searchApi` — search (text+filters+semantic), semanticSearch
- `tagApi` — getCategories, getValues, addTag, removeTag, getStats
- `importApi` — upload, confirm, status

Helper functions:
- `getImageUrl(image)` → `/api/v1/images/{id}/file`
- `getThumbnailUrl(image)` → `/api/v1/images/{id}/thumbnail`

## Filter Logic

Filters are applied server-side. The frontend sends query parameters:
- **Authors:** `authors=czepeku&authors=2mtt` → OR (match any)
- **Tags:** `tags=lighting:night&tags=season:winter` → OR within same category, AND across categories
- **Colors:** `colors=#1a2b3c&colors=#ff0000` → OR (match any)
- **Gridded:** `gridded=true` or `gridded=false`
- **Text:** `text=island` → LIKE search on name, filename, author
- **Semantic:** `semantic=dark cave with water` → CLIP embedding search

## Types (`types/index.ts`)

All interfaces mirror the backend Pydantic schemas. Key types:
- `Image`, `Tag`, `Color`, `VariantGroup`, `TagCategory`
- `SearchParams`, `SearchResult` (includes optional `scores` dict for semantic search)
- `ViewMode`, `ImageGroup` (client-side grouped view types)
- `ImportUploadResponse`, `ImportVariantGroup`, `ImportFileInfo`
- `ImportConfirmRequest`, `ImportJobResponse`, `ImportGroupStatus`
