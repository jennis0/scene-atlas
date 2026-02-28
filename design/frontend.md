# Frontend Architecture

## Overview

A React single-page application for browsing, searching, and importing battlemap images. Built with TypeScript, Vite, Tailwind CSS, and Radix UI. Runs in both web browsers and Electron.

See also:
- [visual-language.md](visual-language.md) — shared styling patterns across all card components
- [group-view.md](group-view.md) — grouped view design and architecture
- [electron.md](electron.md) — Electron-specific windowing, IPC, and desktop mode

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite (dev server at :5173, proxies `/api` → :8000) |
| Styling | Tailwind CSS |
| UI Primitives | Radix UI (Dialog, Sheet, Checkbox, DropdownMenu, Popover) |
| Server State | React Query (`@tanstack/react-query`) |
| Virtualisation | `@tanstack/react-virtual` (row-based virtualisation) |
| HTTP Client | axios |

## Directory Structure

```
frontend/src/
├── App.tsx                    # Router setup (HashRouter)
├── main.tsx                   # Entry point
├── index.css                  # Tailwind base + design tokens
├── electron.d.ts              # Type declarations for window.electronAPI
├── components/
│   ├── ui/                    # Reusable primitives
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── dialog.tsx
│   │   ├── sheet.tsx
│   │   ├── popover.tsx
│   │   ├── dropdown-menu.tsx
│   │   ├── checkbox.tsx
│   │   ├── badge.tsx
│   │   ├── card.tsx
│   │   ├── confirm-dialog.tsx
│   │   ├── error-alert.tsx
│   │   └── video-indicator.tsx
│   ├── import/                # Import-specific sub-components
│   │   ├── FileCard.tsx           # Image card in gallery/viewer
│   │   ├── FileToolbar.tsx        # Toolbar for file operations
│   │   ├── ImportFileCard.tsx     # File card in import dialog
│   │   ├── ImportFileToolbar.tsx  # Import-specific toolbar
│   │   ├── ImportGroupContent.tsx # Group content pane
│   │   ├── ImportGroupNav.tsx     # Tabbed group navigation
│   │   ├── ImportUploadPane.tsx   # Upload drop zone
│   │   ├── ImportDonePane.tsx     # Completion summary
│   │   ├── MetadataForm.tsx       # Author/name form for groups
│   │   ├── TagPicker.tsx          # Tag selection widget
│   │   ├── GridToggle.tsx         # Grid on/off toggle
│   │   ├── GridSizeInput.tsx      # Grid dimensions input
│   │   ├── tagColors.ts           # Tag color palette + lookup
│   │   ├── fileFilter.ts          # File search/filter logic
│   │   └── types.ts               # Import-specific types
│   ├── ActivityDock.tsx       # Import + background job status dock
│   ├── DesktopGate.tsx        # Electron: wait for backend ready
│   ├── EditGroupDialog.tsx    # Post-import group metadata editing
│   ├── ErrorBoundary.tsx      # React error boundary
│   ├── FilterMenuContent.tsx  # Filter menu structure (tags, authors, colors)
│   ├── GalleryFilterPanel.tsx # Filter sidebar (Sheet wrapper)
│   ├── GridFilterIcons.tsx    # Grid state filter icons
│   ├── GroupCard.tsx          # Hero + mosaic card for image group
│   ├── GroupGrid.tsx          # Virtualized group grid
│   ├── ImageGrid.tsx          # Virtualized individual image grid
│   ├── ImageViewer.tsx        # Full-screen image viewer
│   ├── ImportDialog.tsx       # Import flow (upload → preview → process)
│   ├── LoadingScreen.tsx      # Electron: loading/error splash
│   ├── MergeGroupPicker.tsx   # Group merge selection dialog
│   ├── SceneTile.tsx          # Clickable scene thumbnail tile
│   ├── SubgroupDropdown.tsx   # Subgroup selector dropdown
│   ├── SubgroupHeading.tsx    # Subgroup section heading
│   ├── SystemInfoDialog.tsx   # System info + data dir settings
│   └── TagManagementDialog.tsx # Tag category CRUD dialog
├── contexts/
│   └── TagColorContext.tsx    # DB-driven tag color provider
├── hooks/
│   ├── useActiveImports.ts    # Active import polling + status
│   ├── useAppMode.ts          # Detect Electron vs browser mode
│   ├── useBackgroundJobs.ts   # Global background job state
│   ├── useFileEditing.ts      # In-place editing of import metadata
│   ├── useImageGrouping.ts    # Transforms flat Image[] → ImageGroup[]
│   ├── useImportPersistence.ts # LocalStorage for draft imports
│   ├── useImportPolling.ts    # Import status polling
│   ├── useImportState.ts      # Complex import state machine
│   ├── useImportUpload.ts     # File upload management
│   └── useJobPolling.ts       # Background job polling
├── lib/
│   ├── api.ts                 # Axios instance + all API functions
│   ├── apiBase.ts             # Dynamic base URL (Electron port negotiation)
│   ├── appMode.ts             # App mode detection utilities
│   ├── categoryIcons.ts       # Tag category → Lucide icon mapping
│   ├── colorPalette.ts        # Tailwind color presets for tag categories
│   ├── constants.ts           # Shared constants
│   ├── fsEntryTraversal.ts    # Electron: folder traversal via IPC
│   ├── getErrorMessage.ts     # Error message extraction helper
│   ├── hashFile.ts            # Client-side SHA-256 file hashing
│   ├── importStorage.ts       # LocalStorage helpers for import state
│   ├── mimeCheck.ts           # File type validation
│   └── utils.ts               # Tailwind cn() helper
├── pages/
│   └── Gallery.tsx            # Main page: search, filters, grid, import
├── types/
│   └── index.ts               # TypeScript interfaces matching backend schemas
└── test/
    ├── setup.ts               # Vitest setup
    └── renderWithProviders.tsx # Test render helper with providers
```

## Key Components

### Gallery (`pages/Gallery.tsx`)
The main page. Contains:
- **Search bar** — text search with toggle between text/semantic mode
- **View mode toggle** — switches between Individual (flat grid) and Grouped (hero+mosaic) views
- **Filter panel** (Sheet/sidebar) — author checkboxes, tag checkboxes grouped by category, color filters, grid state filter, image/media type filters. Filter search input to narrow long lists.
- **Import button** — opens ImportDialog
- **Image grid or group grid** — renders filtered/searched images in selected view mode
- **Image viewer** — modal for full-screen viewing with variant switching

**State management:** All filter/search state is local `useState`. Image data fetched via React Query. View mode state controls which grid component renders. The `useImageGrouping` hook transforms flat results into groups client-side.

### ImportDialog (`components/ImportDialog.tsx`)
Group management tool for organizing files before import. Per-file metadata editing (tags, grid, name) is deferred to post-import via `ImageViewer` and `EditGroupDialog`.

1. **Upload** — file picker (files or folder via `webkitdirectory`) + zip support. Uploads to `/imports/upload`, gets back grouped variant info.
2. **Preview** — tabbed view (one tab per detected image group). Each tab: editable author + group name, compact file cards (`ImportFileCard`) with thumbnail/name/type toggle, simplified toolbar (`ImportFileToolbar`) with search/filter/bulk actions for group management. "Import This Group" or "Import All" buttons.
3. **Processing/Done** — progress per group, completion summary. Clicking completed job in ActivityDock opens `EditGroupDialog` for post-import metadata review.

State is preserved if dialog is closed during processing (re-open to check progress).

Sub-components live in `components/import/` to keep the import flow self-contained.

### ActivityDock (`components/ActivityDock.tsx`)
Floating bottom-right panel showing import and background job status. Collapsed state shows a pill with spinner + count badge. Expanded state shows job cards with progress bars and status indicators. See [visual-language.md](visual-language.md) for the dock pattern.

### ImageGrid (`components/ImageGrid.tsx`)
Virtualized grid of individual image cards (200px wide, square thumbnails). Each card has an always-visible metadata bar showing name, author, and up to 3 tag badges.

### GroupGrid + GroupCard (`components/GroupGrid.tsx`, `GroupCard.tsx`)
Virtualized grid of image group cards (420px wide). Each card shows a hero image (60% width) + mosaic of scene thumbnails (40% width) with an always-visible metadata bar. See [group-view.md](group-view.md).

### ImageViewer (`components/ImageViewer.tsx`)
Full-screen overlay for viewing an image at full resolution. Sidebar shows:
- **Fixed metadata header**: name, author, subgroup badge, grid badge (hidden for scenes), filename, tags, dominant colors, dimensions
- **Scrollable scene panel**: scenes partitioned by `subgroup` into labelled sections, each with clickable tiles that switch the viewed image

### Desktop Components
- **DesktopGate** — Electron-only wrapper that waits for the `backend-ready` IPC signal before rendering the app. Shows `LoadingScreen` during sidecar startup.
- **LoadingScreen** — Splash screen with loading spinner or error message for backend startup failures.
- **SystemInfoDialog** — Displays storage usage, data directory path, and settings (data dir change triggers app relaunch via Electron IPC).

### TagManagementDialog (`components/TagManagementDialog.tsx`)
Category list with colored dots. Category editor with name, description, Tailwind color swatch picker, and tag value CRUD. Inline confirmation for destructive actions showing affected image counts.

### useImageGrouping (`hooks/useImageGrouping.ts`)
React hook that transforms a flat `Image[]` into `ImageGroup[]`. Handles bucketing by `group_id`, hero selection (score-based for semantic search, positional otherwise), mosaic image selection, tag aggregation, and cross-referencing `allImages` for true group scene counts.

## API Client (`lib/api.ts`)

Axios instance with:
- Base URL: dynamic — `/api/v1` in browser (proxied by Vite in dev), `http://localhost:{port}/api/v1` in Electron (port from backend-ready IPC)
- `paramsSerializer: { indexes: null }` for FastAPI array parameter compatibility (sends `tags=a&tags=b` instead of `tags[0]=a&tags[1]=b`)

Key API groups:
- `imageApi` — list, get, patch, delete, getScenes, getAuthors, backfillGrids
- `searchApi` — search (text+filters+semantic), facets, rebuildEmbeddings
- `tagApi` — categories CRUD, tag value CRUD, retag-all, stats
- `importApi` — init, upload, confirm, confirmAll, status, analysis, finalize, cancel, active, checkHashes
- `groupApi` — search, get, edit, delete, merge, moveImages, download
- `jobApi` — list, get
- `exportApi` — library export
- `systemApi` — info, deleteLibrary, resetTags
- `settingsApi` — get, patch

Helper functions:
- `getImageUrl(image)` → `/api/v1/images/{id}/file`
- `getThumbnailUrl(image)` → `/api/v1/images/{id}/thumbnail`

## Filter Logic

Filters are applied server-side. The frontend sends query parameters:
- **Authors:** `authors=czepeku&authors=2mtt` → OR (match any)
- **Tags:** `tags=lighting:night&tags=season:winter` → OR within same category, AND across categories
- **Exclude tags:** `xtags=state:ruined` → exclude images with these tags
- **Colors:** `colors=#1a2b3c&colors=#ff0000` → OR (match any)
- **Gridded:** `gridded=true` or `gridded=false` or `gridded=unknown`
- **Image type:** `image_type=battlemap` or `image_type=scene`
- **Media type:** `media_type=image` or `media_type=video`
- **Text:** `text=island` → FTS5 search on pre-tokenized fields
- **Semantic:** `semantic=dark cave with water` → CLIP embedding search

## Types (`types/index.ts`)

All interfaces mirror the backend Pydantic schemas. Key types:
- `Image`, `Tag`, `Color`, `ImageGroup` (DB model), `TagCategory`
- `SearchParams`, `SearchResult` (includes optional `scores` dict for semantic search)
- `ViewMode`, `ImageGroup` (client-side grouped view types)
- `ImportUploadResponse`, `ImportGroup`, `ImportFileInfo`
- `ImportConfirmRequest`, `ImportJobResponse`, `ImportGroupStatus`
- `BackgroundJob`, `JobStatus`
