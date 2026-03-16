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
│   │   ├── ImportUploadPane.tsx   # Upload drop zone
│   │   ├── ImportDonePane.tsx     # Completion summary
│   │   ├── MetadataForm.tsx       # Author/name form for groups
│   │   ├── TagPicker.tsx          # Tag selection widget
│   │   ├── GridToggle.tsx         # Grid on/off toggle
│   │   ├── GridSizeInput.tsx      # Grid dimensions input
│   │   ├── tagColors.ts           # Tag color palette + lookup
│   │   ├── fileFilter.ts          # File search/filter logic
│   │   ├── types.ts               # Import-specific types
│   │   └── shared/
│   │       ├── FileToolbarCore.tsx     # Shared toolbar primitives
│   │       ├── FileCardExcludedState.tsx # Excluded file visual state
│   │       ├── FileCardThumbnail.tsx   # Shared thumbnail component
│   │       ├── FileCardLightbox.tsx    # Lightbox for file cards
│   │       ├── TypeToggle.tsx          # Image type toggle button
│   │       ├── TypeToggleInline.tsx    # Inline type toggle variant
│   │       ├── SubgroupRow.tsx         # Subgroup display row
│   │       └── dnd/                    # Drag-and-drop infrastructure
│   │           ├── DraggableFileCardWrapper.tsx
│   │           ├── DroppableGroupRow.tsx
│   │           ├── DroppableSubgroupSection.tsx
│   │           └── DragOverlayContent.tsx
│   ├── settings/               # Settings UI components
│   │   ├── SettingRow.tsx          # Individual setting row
│   │   ├── SettingsTabContent.tsx  # Settings tab panel content
│   │   └── RestartBadge.tsx        # Badge indicating restart required
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
│   ├── GalleryHeader.tsx       # Main gallery header (search, view toggle, actions)
│   ├── GroupPickerShell.tsx    # Wrapper for merge picker UI
│   ├── GroupSidebarShell.tsx   # Sidebar shell for group browsing
│   ├── ImportSummaryDialog.tsx # Import completion summary (errors, warnings, skipped)
│   ├── MergeGroupPicker.tsx   # Group merge selection dialog
│   ├── SceneTile.tsx          # Clickable scene thumbnail tile
│   ├── SubgroupDropdown.tsx   # Subgroup selector dropdown
│   ├── SubgroupHeading.tsx    # Subgroup section heading
│   ├── LibraryInfoDialog.tsx   # System info + data dir settings
│   └── TagManagementDialog.tsx # Tag category CRUD dialog
├── contexts/
│   ├── TagColorContext.tsx    # DB-driven tag color provider
│   └── ThemeContext.tsx       # Light/dark mode toggle (stored in localStorage)
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
│   ├── useJobPolling.ts       # Background job polling
│   ├── useGroupSearch.ts      # Group search with pagination
│   ├── useEditGroupDnd.ts     # Drag-and-drop for edit group dialog
│   ├── useEditGroupOperations.ts # Edit group mutation operations
│   ├── useEditGroupLoad.ts    # Load group data for editing
│   ├── useGalleryDialogs.ts   # Manages multiple dialog open/close state
│   ├── useGallerySearch.ts    # Gallery search with React Query
│   ├── useGroupSidebarMultiselect.ts # Multi-select in group sidebar
│   ├── useImportProgressPolling.ts   # Import progress tracking for live review
│   └── useSettingsDraft.ts    # Settings UI draft state management
├── lib/
│   ├── api/                   # Modular API client directory (_client.ts, per-domain modules like imageApi.ts, searchApi.ts, etc., and index.ts barrel export)
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
│   ├── queryKeys.ts           # Centralized query key definitions + cache invalidation helpers
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
- **Relevance slider** (grouped view only) — filters groups by semantic score threshold. Instant client-side filter when raising (stricter), debounced 400ms refetch when lowering (lenient). Hidden in browse mode (no scores).
- **Import button** — opens ImportDialog
- **Edit All button** (grouped view only) — enabled when ≤500 groups. Fetches all matching images via `/search/groups?include_all_image_ids=true`, seeds EditGroupDialog for mass-editing.
- **Image grid or group grid** — renders filtered/searched images in selected view mode
- **Image viewer** — modal for full-screen viewing with variant switching

**State management:** Filter/search state managed by `useGallerySearch` hook with React Query. View mode state controls which grid component renders. Grouped view fetches directly from `/search/groups` endpoint (no client-side grouping).

**Edit All flow:**
1. User clicks "Edit All" in grouped view (≤500 groups)
2. `handleOpenMassEdit` fetches groups with `include_all_image_ids: true`
3. Maps image IDs to `SeedImage[]` objects
4. Opens EditGroupDialog with seedImages prop
5. Dialog marks non-seeded images as `outOfScope` (visible but protected from bulk edits)
6. User can bring images into scope by clicking them individually

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
- **LibraryInfoDialog** — Displays storage usage, data directory path, and settings (data dir change triggers app relaunch via Electron IPC).

### TagManagementDialog (`components/TagManagementDialog.tsx`)
Category list with colored dots. Category editor with name, description, Tailwind color swatch picker, and tag value CRUD. Inline confirmation for destructive actions showing affected image counts.

### useImageGrouping (`hooks/useImageGrouping.ts`)
React hook that transforms a flat `Image[]` into `ImageGroup[]`. Handles bucketing by `group_id`, hero selection (score-based for semantic search, positional otherwise), mosaic image selection, tag aggregation, and cross-referencing `allImages` for true group scene counts.

## API Client (`lib/api/`)

Axios instance with:
- Base URL: dynamic — `/api/v1` in browser (proxied by Vite in dev), `http://localhost:{port}/api/v1` in Electron (port from backend-ready IPC)
- `paramsSerializer: { indexes: null }` for FastAPI array parameter compatibility (sends `tags=a&tags=b` instead of `tags[0]=a&tags[1]=b`)

Key API groups:
- `imageApi` — list, get, patch, delete, getScenes, getAuthors, backfillGrids
- `searchApi` — search (flat Image[], text+filters+semantic), groups (grouped view with pagination), facets, rebuildEmbeddings
- `tagApi` — categories CRUD, tag value CRUD, retag-all, stats
- `importApi` — init, upload, confirm, confirmAll, status, analysis, finalize, cancel, active, checkHashes
- `groupApi` — get, edit, delete, merge, moveImages, download
- `jobApi` — list, get
- `systemApi` — info, deleteLibrary, resetTags
- `settingsApi` — get, patch
- `modelsApi` — setup status, list models, set active, download, delete embeddings

**searchApi.groups()** — Grouped search with pagination
- Returns pre-grouped results with image IDs and semantic scores
- Supports all search parameters (query, filters, min_score)
- When `include_all_image_ids: true`, populates `all_image_ids` for Edit All seeding
- Used for grouped view gallery and Edit All functionality

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

**Image & Search:**
- `Image`, `Tag`, `Color`, `ImageGroup` (DB model), `TagCategory`
- `SearchParams`, `SearchResult` (flat image results with optional `scores` dict)
- `GroupSearchResult`, `GroupSearchResponse` (grouped results with pagination)
- `SeedImage` — minimal image reference `{ id: number; group_id: number | null }` used for Edit All seeding

**View Modes:**
- `ViewMode` — `'individual' | 'grouped'`
- `ImageGroup` — client-side grouped view type (rendered from GroupSearchResult + full Image objects)

**Import & Jobs:**
- `ImportUploadResponse`, `ImportGroup`, `ImportFileInfo`
- `ImportConfirmRequest`, `ImportJobResponse`, `ImportGroupStatus`
- `BackgroundJob`, `JobStatus`
