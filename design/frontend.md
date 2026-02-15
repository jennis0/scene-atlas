# Frontend Architecture

## Overview

A React single-page application for browsing, searching, and importing battlemap images. Built with TypeScript, Vite, Tailwind CSS, and Radix UI.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite (dev server at :5173, proxies `/api` → :8000) |
| Styling | Tailwind CSS |
| UI Primitives | Radix UI (Dialog, Sheet, Checkbox, DropdownMenu) |
| Server State | React Query (`@tanstack/react-query`) |
| HTTP Client | axios |

## Directory Structure

```
frontend/src/
├── components/
│   ├── ui/               # Reusable primitives (button, input, dialog, sheet, badge, etc.)
│   ├── ImageGrid.tsx     # Masonry/grid image layout with lazy loading
│   ├── ImageViewer.tsx   # Full-screen image viewer with keyboard nav
│   ├── ImportDialog.tsx  # Web import flow (upload, preview, confirm)
│   └── SearchBar.tsx     # Search input component
├── lib/
│   ├── api.ts            # Axios instance + all API functions
│   └── utils.ts          # Tailwind cn() helper
├── pages/
│   ├── Gallery.tsx       # Main page: search, filters, grid, import
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
- **Filter panel** (Sheet/sidebar) — author checkboxes, tag checkboxes grouped by category, color filters. Filter search input to narrow long lists.
- **Import button** — opens ImportDialog
- **Image grid** — renders filtered/searched images
- **Image viewer** — modal for full-screen viewing with arrow key navigation

**State management:** All filter/search state is local `useState`. Image data fetched via React Query. No global state store.

### ImportDialog (`components/ImportDialog.tsx`)
Three-state dialog for the web import flow:

1. **Upload** — file picker (files or folder via `webkitdirectory`) + zip support. Uploads to `/imports/upload`, gets back grouped variant info.
2. **Preview** — tabbed view (one tab per detected variant group). Each tab: editable author + group name fields, file list with detected tags/grid badges. "Import This Group" or "Import All" buttons.
3. **Processing/Done** — progress per group, completion summary.

State is preserved if dialog is closed during processing (re-open to check progress). An `onActiveChange` callback notifies the Gallery to show a pulsing indicator on the Import button.

### ImageGrid (`components/ImageGrid.tsx`)
Renders images in a responsive grid. Each card shows thumbnail, name, author, and tag badges.

### ImageViewer (`components/ImageViewer.tsx`)
Full-screen overlay for viewing an image. Supports previous/next navigation via arrow keys.

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
- `SearchParams`, `SearchResult`, `SemanticSearchResult`
- `ImportUploadResponse`, `ImportVariantGroup`, `ImportFileInfo`
- `ImportConfirmRequest`, `ImportJobResponse`, `ImportGroupStatus`
