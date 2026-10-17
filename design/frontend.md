# Frontend Architecture

A React single-page application for browsing, searching and importing scenes. The same build runs in a browser (server mode) and inside Electron (app mode).

See also:
- [visual-language.md](visual-language.md) — tokens, typography and card/dialog styling
- [dialog-focus-management.md](dialog-focus-management.md) — focus handling in dialogs
- [search.md](search.md) — backend search, ranking and filters
- [ingestion.md](ingestion.md) — import protocol and ingest pipeline
- [electron.md](electron.md) — Electron windowing, IPC and desktop mode

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite (dev server on :5173, proxies `/api` to :8000) |
| Styling | Tailwind CSS 3, tokens in `src/index.css` |
| UI primitives | Own components in `components/ui/`; Radix only for checkbox, dropdown menu and popover |
| Server state | TanStack Query (`@tanstack/react-query`) |
| Virtualisation | `@tanstack/react-virtual` (row-based) |
| Drag and drop | `@dnd-kit` (edit-group dialog) |
| HTTP | axios |
| Toasts | sonner |
| Tests | Vitest + Testing Library (`src/test/` holds setup and helpers) |

## Directory Layout

```
frontend/src/
├── App.tsx            HashRouter, setup-wizard gate (server mode), theme
├── main.tsx           Entry point, providers
├── index.css          Tailwind base + design tokens
├── electron.d.ts      Types for window.electronAPI
├── pages/Gallery.tsx  The only page: header, filters, grid, viewer, dialogs
├── components/
│   ├── ui/            Primitives: button, input, dialog (custom portal), confirm-dialog,
│   │                  checkbox / dropdown-menu / popover (Radix wrappers), panel-title,
│   │                  video-indicator
│   ├── viewer/        ImageViewer pieces: stage, toolbar, name editor, properties, tags, scene panel
│   ├── edit-group/    EditGroupDialog pieces: header, sidebar, file grid, footer, confirmations,
│   │                  useEditScope
│   ├── imports/       Import dialog, progress ledger, job rows, import report
│   ├── import/        Shared file-card, toolbar, tag/grid pickers and dnd pieces, used by the
│   │                  edit-group dialog, viewer and filter UI (name predates the import rewrite)
│   ├── settings/      Settings tab content and setting controls
│   ├── setup/         First-run wizard: model choice and tag-pack step
│   └── *.tsx          Gallery-level components (header, grids, cards, viewer, dialogs, dock)
├── contexts/          ThemeContext (light/dark, localStorage), TagColorContext (DB-driven colours)
├── hooks/             Search, dialog state, edit-group, settings and job-polling hooks
├── lib/
│   ├── api/           axios client (_client.ts), one module per backend area, urls.ts, index.ts barrel
│   ├── import/        ImportManager, importClient, hasher + hash.worker, React bindings
│   ├── apiBase.ts     API base URL (Electron port negotiation)
│   ├── appMode.ts     'app' (Electron) vs 'server'
│   ├── queryKeys.ts   Query keys and invalidation helpers
│   └── …              Small utilities (constants, formatting, downloads, icons, colours)
├── types/index.ts     Interfaces mirroring backend schemas (snake_case field names)
└── test/              Vitest setup, render helper, import fakes
```

Tests sit next to the code they cover (`*.test.ts(x)`).

## Gallery

`pages/Gallery.tsx` composes the page. Main pieces:

- **GalleryHeader** — search input, sort, view-mode toggle (individual / grouped), image-type toggle, relevance slider, filter button, import, tag management, library info, Edit All.
- **GalleryFilterPanel / FilterMenuContent** — tag, author, colour, grid and media filters, fed by `GET /search/facets`.
- **ImageGrid** (individual view) — virtualised grid of `SceneTile`s.
- **GroupGrid** (grouped view) — virtualised grid of `GroupCard`s with infinite scroll (an `IntersectionObserver` sentinel in Gallery calls `fetchNextPage`).
- **ImageViewer** — full-screen viewer with metadata editing and a scene panel for the image's group.
- **EditGroupDialog** — edit one group, or many via Edit All.
- **ImportDialog**, **ActivityDock**, **TagManagementDialog**, **LibraryInfoDialog**, **EmptyLibraryWelcome**.

On first run (any mode) `App.tsx` shows **ModelSetupScreen** until a model and tag packs are set up. In Electron the startup screen is `electron/loading.html`, outside React.

### Search state (`hooks/useGallerySearch.ts`)

Owns the query, filters, sort, view mode and relevance threshold, and builds `SearchParams`.

- **Query prefixes.** Search is hybrid by default. A leading `~` is stripped and sends `semantic_only=true` (visual search); a leading `=` is stripped and sends `text_only=true` (keyword search). The input placeholder documents both, plus `"quotes"` for exact phrases.
- **URL state.** Query, filters and image type are mirrored into the URL (`q`, `tag`, `xtag`, `author`, `xauthor`, `gridded`, `color`, `media_type`, `image_type`) so searches can be bookmarked.
- **Sort.** `created_at desc` by default. Submitting a query switches to `relevance`; clearing it restores the saved sort. Non-relevance sorts persist in localStorage.
- **Relevance slider.** Shown when there is a query that is not `=`. Filters on the RRF score returned by the API, client-side. In grouped view, raising the threshold filters loaded groups instantly; lowering it resets the paged query after 400 ms so more groups load.
- **Individual view** calls `GET /search/` (limit 500). **Grouped view** uses `hooks/useGroupSearch.ts`, which pages `GET /search/groups` 50 groups at a time.

### Filter parameters

Filters are applied server-side. Parameter names match `SearchParams` in `types/index.ts` and the search API (`backend/app/api/search.py`); arrays are sent as repeated keys (`tags=a&tags=b`, via axios `paramsSerializer: { indexes: null }`).

| Parameter | Meaning |
|-----------|---------|
| `query` | Hybrid query (prefix already stripped) |
| `semantic_only` / `text_only` | Set by `~` / `=` |
| `tags` / `exclude_tags` | `category:value`. OR within a category, AND across categories |
| `authors` / `exclude_authors` | OR across authors |
| `colors` | Hex colours, OR |
| `gridded`, `gridded_unknown`, `grid_type` | Grid state (`grid_type` is `square` or `hex`) |
| `image_types` | `battlemap`, `scene` |
| `media_types` | `image`, `video` |
| `sort_by` / `sort_dir` | `created_at`, `name`, `relevance` / `asc`, `desc` |
| `limit` / `offset` | Paging |
| `include_all_image_ids` | `/search/groups` only; used by Edit All |

## Grouped View

Groups are formed and paged on the server (`search_service.browse_groups` / `search_groups`). Each `GroupSearchResult` carries `hero_image`, up to four `mosaic_images`, `total_scenes`, `matching_scenes`, `best_score` and optionally `all_image_ids`. `useGroupSearch` maps results to the camelCase client type `ImageGroup`.

- **No query:** groups in `sort_by` order (`relevance` falls back to `created_at`). Hero is the group's primary image, else its first image; mosaic is the next images. `best_score` is null.
- **With a query:** groups ranked by their best-matching image. Hero is the best match; mosaic is the next best matches, topped up with the group's newest other images. `matching_scenes` may be less than `total_scenes`.

### GroupCard layout

- 420 px wide, 160 px image area (`GroupGrid` constants). Hero takes 60% of the width; the mosaic takes the rest.
- The mosaic uses only 1, 2 or 4 tiles so a 2-column grid never has an empty cell. When scenes remain beyond those shown, the last tile shows "+N more".
- Name, author and scene count ("N scenes", or "M of N scenes" when filtered) sit in a gradient overlay over the hero, not in a separate bar.
- Hover reveals an action menu (edit, merge, download, delete).

### Edit All

Available in grouped view when the result has at most 500 groups (the `/search/groups` page limit). Gallery fetches `/search/groups` with `include_all_image_ids=true` and passes `SeedImage[]` (`{ id, group_id }`) to `EditGroupDialog`. With a query, `all_image_ids` holds only matching images; the dialog loads the full groups and marks other images `outOfScope` (shown, but excluded from bulk edits until selected individually).

## Image Viewer

`components/ImageViewer.tsx` owns the queries, mutations, keyboard handling and navigation
reset; the presentational pieces live in `components/viewer/`. The key handler ignores keys
while the name or subgroup is being edited, while focus is in an input, and while any dialog
is open (`isAnyDialogOpen()` from `ui/dialogStack.ts`). The sidebar has a fixed metadata header (name, author, subgroup, grid state for battlemaps, filename, tags, colours, dimensions) and an independently scrolling scene panel for the group:

- Scenes are partitioned by `subgroup`; scenes without one go under "Other".
- A group with a single section shows it without subgroup headers.
- Tiles are `SceneTile`s; clicking one switches the viewed image.
- Search, the Maps/Scenes toggle and the filter menu are client-side, in `hooks/useSceneFilters.ts`.
  It filters with the same `applyFileFilter` (`components/import/fileFilter.ts`) as the edit
  dialog, with its own text matcher (name, subgroup or filename stem).

## Edit Group Dialog

`components/EditGroupDialog.tsx` wires together `useFileEditing` (editor state and bulk edits),
`useEditGroupLoad`, `useEditGroupOperations` (API calls and auto-save), `useEditGroupDnd` and
`useGroupSidebarMultiselect`. `edit-group/useEditScope.ts` derives what is in view: the
multi-selected groups, every group (All tab) or the active group. Bulk edits take a `BulkScope`
(one group id, several, or `null` for all).

Confirmations (inline delete, merge picker, modal merges and deletes) are one `PendingConfirm`
state in the dialog, so only one is open at a time. Operations a confirmation gates resolve to
a success flag; the dialog closes the confirmation only on success.

## Imports

All import state lives in `lib/import/`, outside the React tree:

- **ImportManager** — single owner of import state. Describes picked files, uploads archives and files (the hash worker runs ahead of 3 concurrent `PUT`s, with per-file retry), resumes interrupted uploads, polls job summaries (one ETag-aware `GET /imports` poller: 1 s while active, 5 s when the tab is hidden, 30 s when idle), and guards `beforeunload` while bytes are outstanding. Nothing is persisted locally; the server owns the lifecycle.
- **importClient** — typed HTTP client for the imports API; only ImportManager calls it.
- **hasher / hash.worker** — SHA-256 in a Web Worker, used only to skip uploading files the library already has. Skipped outside secure contexts and for very large files; the server always re-hashes.
- **useImports** — `useSyncExternalStore` bindings. Components read import state only through these hooks.

`components/imports/ImportDialog.tsx` is one dialog with three views: start (pick battlemap or scene, then files, folders or zips), progress (upload/ingest progress, problems, group ledger), and, once the job finishes, the result in the same frame (`ImportResultView`): Groups, Problems (by reason, Retry), Already in library (Import as new copies) and Skipped, opening on Problems when files failed, with Undo import (confirmed), Review in editor (primary) and Done (closes, and clears a finished import from the activity list). Clicking a group, in progress or result, opens the review editor on that group (`startGroupId`). Closing the dialog never stops an import.

A **clean finish** (`isCleanFinish`: completed, no failures, no files already in the library, upload not cut short) skips the dialog: the finished toast's "Review" and a click on the import in `ActivityDock` open the review editor directly; anything else opens the dialog. Undo is also on the dock row (confirmed), so it stays reachable without the dialog. `ActivityDock` shows imports (plus a queue banner when system-paused) and background jobs.

The review editor (`EditGroupDialog` with `groupIds`) first fetches every group's summary (`POST /groups/summaries`: name, count, image ids) so the whole import is listed at once, then fetches files with `POST /groups/details` in a first batch of 8 and then batches of 40, one request at a time (the backend serialises reads), appending each as it lands (each append re-renders every file card, which is what limits large imports). Groups still loading show as placeholder rows; clicking one fetches it next and opens it. Placeholders are not editor state, so nothing can save a group whose files are not loaded (saves send the full list of images to keep). While groups are loading, All says that its changes apply only to the groups already loaded. A start group is fetched first and listed first. Imports above 500 images open on the first group rather than All. The editor resets on close. Mass edit fetches its groups through `POST /groups/details` too. From 60 files, the file grid renders only the rows on screen (subgroup headings and pairs of cards), so a large All view keeps a small DOM. Plan for the rest: [editor-metadata-first.md](editor-metadata-first.md). See [ingestion.md](ingestion.md) for the protocol.

## Dialogs

`components/ui/dialog.tsx` is a custom modal rendered through `createPortal` (not Radix); `confirm-dialog.tsx` builds on it. Focus handling is described in [dialog-focus-management.md](dialog-focus-management.md).

## API Client (`lib/api/`)

- `_client.ts` — axios instance with base URL `/api/v1`. Every mode is same-origin: server mode, the Vite dev proxy, and Electron (the sidecar serves the UI).
- One module per backend area: `searchApi`, `imageApi`, `groupApi`, `tagApi`, `jobApi`, `systemApi`, `settingsApi`, `modelsApi`. Imports use `lib/import/importClient.ts` instead.
- `urls.ts` — file, thumbnail, group-download and library-export URLs.

Query keys and the helpers that invalidate related caches after mutations live in `lib/queryKeys.ts`.

## Types (`types/index.ts`)

Interfaces mirror the backend Pydantic schemas and keep their snake_case field names (`group_id`, `hero_image`, `total_groups`, …). Client-only types use camelCase (`ImageGroup`, `ViewMode`). Import types live in `lib/import/types.ts`.
