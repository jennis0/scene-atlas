# Scene Atlas: Status and Roadmap

**Last updated:** 2026-10-19

This is the single source of truth for what exists, what is in progress and what is outstanding. Architecture detail lives in the docs linked from [README.md](README.md).

## What Scene Atlas does

A tool for viewing and searching large collections of tabletop RPG scenes (battlemaps, vistas, portraits, encounter art):

- **Search** by name, author, tags, colour, grid type and semantic image description (CLIP / SigLIP2), with hybrid ranking.
- **Import** files, folders or zips through the web UI, with server-side group detection, duplicate detection and resumable uploads.
- **Groups** of related images (e.g. seasonal variants of a map), shown as hero + mosaic cards.
- **Type-aware processing**: battlemaps get grid detection; scenes skip it.
- **Three deployment modes**: Electron desktop app, web server behind a reverse proxy, developer mode.

## Feature inventory

| Feature | Key files | Notes |
|---|---|---|
| Hybrid search (keyword + semantic) | `backend/app/services/search_service.py`, `backend/app/api/search.py`, `frontend/src/hooks/useGallerySearch.ts` | FTS5 + embeddings fused with RRF; `~` (visual only) and `=` (keyword only) prefixes. [search.md](search.md) |
| FTS phrase matching and aliases | `backend/app/services/fts_service.py` | Quoted phrases use FTS5 adjacency and skip alias expansion |
| Grouped search | `GET /search/groups`, `frontend/src/hooks/useGroupSearch.ts` | Server-side grouping with hero + mosaic, 50 groups per page, infinite scroll |
| Colour search | `backend/app/services/color_search.py` | CIE76 delta E over dominant colours in SQL; Settings → Colour match (Close 12 / Similar 25 / Broad 40). [search.md](search.md#colour-search) |
| Import pipeline | `backend/app/api/imports.py`, `backend/pipeline/ingest_*.py`, `frontend/src/lib/import/`, `frontend/src/components/imports/` | Durable per-item queue with a dedicated worker (ADR-018). Auto image type sorts maps / scenes and skips tokens and other art for review (ADR-020). [ingestion.md](ingestion.md) |
| Duplicate detection | `backend/pipeline/image_hashes.py`, `ingest_queue.py`, `ingest_process.py` | Byte and pixel tiers auto-skip; "Import as new copy" override; pHash stored but unused |
| Stored format | `backend/pipeline/stored_format.py` | Optional WebP/JPEG/PNG conversion of new imports (`stored_format`); off by default |
| Group detection and name parsing | `backend/app/services/image_parser.py` | Folder-based + prefix-based. [parser.md](parser.md) |
| Grid detection (ADR-019) | `backend/app/services/grid/`, `backend/app/services/grid_detector.py` | Filename keywords plus image analysis for battlemaps: v3 spectral detector with ONNX classifiers for maps ≥1000 px, legacy detector below; `grid_source` records filename/detector/user. [grid-detection-v3.md](grid-detection-v3.md) |
| Tag system and tag packs | `backend/app/api/tags.py`, `backend/app/services/tag_packs.py`, `frontend/src/components/TagManagementDialog.tsx` | Categories with aliases, colours, icons; installable packs. [tag-packs.md](tag-packs.md) |
| Image viewer | `frontend/src/components/ImageViewer.tsx` | Metadata sidebar; scenes partitioned by subgroup |
| Edit group dialog | `frontend/src/components/EditGroupDialog.tsx` | Drag-and-drop, merge, type toggle, Edit All (up to 500 groups) |
| Export | `backend/app/api/export.py`, `backend/pipeline/export_library.py` | Streamed ZIP of the library; CLI folder export |
| Settings | `frontend/src/components/settings/`, `backend/app/api/settings.py` | DB-backed app settings |
| Activity dock | `frontend/src/components/ActivityDock.tsx`, `frontend/src/components/imports/ImportJobRow.tsx` | Import and background-job progress, connection state |
| Video support | `backend/app/services/video_utils.py` | `.mp4`/`.webm`; first frame for thumbnails and embeddings |
| Multi-model ONNX inference | `backend/app/services/clip_service.py`, `backend/app/services/model_registry.py` | Small (CLIP ViT-B/32, 512-d), medium (SigLIP2-base, 768-d), large (SigLIP2-large, 1024-d). |
| Model download and switching | `backend/app/services/model_download_service.py`, `backend/app/api/models.py`, `frontend/src/components/setup/ModelStep.tsx` | Hugging Face-hosted ONNX; switch pauses ingest and re-embeds. [hf-model-management.md](hf-model-management.md) |
| GPU acceleration | `backend/app/services/ort_providers.py`, `clip_service.py` | `inference_device=auto`; CUDA / DirectML / CoreML / CPU. [gpu-acceleration.md](gpu-acceleration.md) |
| Electron desktop app | `electron/src/`, `backend/pyinstaller/` | Sidecar lifecycle, storage-folder setup. Updates via electron-updater: installs on Windows and AppImage, notifies on macOS and .deb (ADR-021); the user chooses Automatic, Ask first (default) or Off (ADR-025). [electron.md](electron.md#updates) |
| Server update check | `backend/app/services/update_check.py`, `GET /api/v1/system/updates`, `frontend/src/components/settings/UpdatesSection.tsx` | Server mode: daily GitHub check, Settings shows the version and a newer release; `CHECK_FOR_UPDATES=false` turns it off (ADR-023). [backend.md](backend.md#update-check) |
| Maintenance | `backend/app/services/scheduler.py`, `backend/pipeline/maintenance.py`, `ingest_maintenance.py`, `vector_reconcile.py` | Daily backups, 6-hourly ingest cleanup, orphan sweep, vector reconciliation |
| Concurrency control | `backend/app/services/prepare_pool.py`, `memory_budget.py`, `api/dependencies.py` | [resource-management.md](resource-management.md) |
| Security hardening | `backend/app/main.py` (`SecurityHeadersMiddleware`), `backend/app/api/rate_limits.py` | Security headers, rate limits, CORS warning. No built-in authentication. [security.md](security.md) |
| Checks | `.husky/pre-push`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` | Lint + unit tests pre-push; security, integration and frontend build on PRs; manual release with cross-platform tests, E2E and builds. [testing.md](testing.md) |
| Release builds | `.github/workflows/release.yml`, `release-published.yml`, `scripts/build/`, `scripts/release/` | Windows x64 (DirectML), macOS arm64, Linux x64, and a CPU Docker image on GHCR (amd64). Version in the repo, draft releases (ADR-024). [releasing.md](releasing.md) |
| Library setup and the linked library | `backend/app/library_identity.py`, `backend/pipeline/linked_*.py`, `frontend/src/components/setup/LibraryStep.tsx`, `frontend/src/components/settings/LinkedFolderSection.tsx` | Storage in the wizard, one read-only linked folder, library identity and reopening (PR #51, ADR-026). [library-setup.md](library-setup.md) |
| User docs | `docs/` (VitePress, GitHub Pages) | Guide (with Your Library and Settings pages), Deploy, Reference (configuration, how search works, CLI, troubleshooting), Development. Update the guide with any user-facing change |

## In progress

| Work | Where | Notes |
|---|---|---|
| Pre-release code-quality pass | PR #4 (`chore/pre-release-quality`) | [code-quality-baseline.md](code-quality-baseline.md) |
| Tech-debt pass (follow-up to PR #4) | branch `chore/tech-debt` | Clears the previous backlog's debt rows |

## Backlog

| Item | Notes | Priority |
|---|---|---|
| Sidecar size | Windows (2026-10-19): sidecar 610 MB, installer 243 MB ([electron.md](electron.md#build--packaging) has the breakdown and what was cut); Linux ~810 MB before those cuts (2026-10-18), and keeps pyarrow's Flight/Substrait/S3 libraries, which its pyarrow links. Biggest parts: `_lancedb.pyd` 225 MB (grows each release: 47 MB wheel at 0.30, 75 MB at 0.40), opencv 111 MB (grid v3 and video thumbnails), scipy 67 MB (grid detection's `scipy.signal` pulls in optimize and sparse; replacing `find_peaks`/`fftconvolve`/`median_filter` would drop it, at some risk to grid detection). Replacing LanceDB with brute-force numpy search was considered and rejected (2026-10-17): fast enough at 100k images (~6 ms), but re-implementing updates, per-model tables, re-embedding and reconcile isn't worth ~65 MB of download. | Low |
| Verify the sidecar lifecycle on packaged macOS (and Linux in CI) | Windows verified 2026-10-19 by `e2e/packaged`, and Linux locally the same day (WSLg, all seven passing) (graceful stop, which was broken, no orphan after a kill, single instance, storage-change relaunch). The specs are cross-platform; run them on the macOS and Linux (xvfb) Release builds. Not yet covered anywhere: the loading page's message when another backend holds the storage lock. | Medium |
| Windows code signing | Unsigned installers trigger SmartScreen on first install, and an unsigned update is only checked against the sha512 in its own release ([electron.md](electron.md#updates)). SignPath Foundation's free OSS signing is the option; set `win.signtoolOptions.publisherName` with it so electron-updater checks the publisher. | Medium |
| Check SmartScreen on an update | Expected: only the first, manual install warns, because electron-updater's download carries no Mark-of-the-Web. Confirm with one update on a real Windows PC before going live. | High |
| Upgrade test on Linux | Run `e2e/upgrade` on the AppImage build (xvfb, libfuse2): the AppImage installs updates too. | Medium |
| macOS auto-install | Needs signing (below) and a `zip` mac target; then `updateModeFor` can return install on macOS. | Low |
| macOS signing and notarization | The Release workflow signs and notarizes when the `MAC_CERT_P12`, `MAC_CERT_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID` secrets are set; none are yet, so the DMG is unsigned and Gatekeeper blocks first launch. Needs an Apple Developer account. | Medium |
| Serve setup/loading pages from a custom protocol | Would let the `grantFileProtocolExtraPrivileges` fuse go off ([electron.md](electron.md#fuses)). Only `loading.html` is left now that the storage window is gone. | Low |
| Parser: Moonlight Maps file names | `Moonlight_Maps_Demon_Skull_Desert06_25x25_72_[skull,giant,desert].jpg` keeps the DPI (`72`) and the bracketed list in the display name ("Desert 06 72 [skull,giant,desert]"). Strip the DPI after a grid size, and turn a trailing `[a,b,c]` list into tags. Found importing the demo library (design/brand.md, Screenshots). [parser.md](parser.md) | Medium |
| Parser: branded creator folders on first import | A creator folder whose files all carry its name (`leasealair/leasealairMaps_…`), imported as a lone folder before that creator is in the library, is read as one map's group. Pass 0 in [parser.md](parser.md#pass-0-folderfile-paths-group-or-creator) has the numbers. A signal that could separate them: the remainders after the creator's name are many distinct map names, not variants. | Low |
| Parser: prefix grouping on generic words | "Portrait of a Man" and "Portrait of Roberto Castiglione" in one folder were grouped as "Portrait of". Prefix grouping should not fire on a shared prefix that ends in a stop word or is only common words. [parser.md](parser.md) | Low |
| Verify the first-launch warning steps | `docs/deploy/desktop.md` tells users how to open the unsigned installers (SmartScreen "Run anyway"; macOS Open Anyway, or `xattr` if macOS calls the app damaged). Written from platform behaviour, not yet checked against a real release build on each OS. Check at the first release; if macOS reports "damaged", consider ad-hoc signing (`mac.identity: "-"` in `electron-builder.yml`). | Medium |
| Colour threshold default is loose | ΔE 25 reproduces the old HSL 0.35, but a typical map colour matches ~80% of the library and colour-filtered browse is 70–140 ms slower at 56k images than the old in-memory index. ΔE 12–15 is faster and more useful. Settings → Colour match lets users choose Close (12), but the default is still 25. [search.md](search.md) | Medium |
| Embedding status ignores plain downloads | `/embedding-status` reports `loading` only for "Activate model" jobs; a `POST /models/{name}/download` (download without activating) shows `missing` while it runs. Count those jobs too if the UI ever starts one for the active model. | Low |
| Regenerate thumbnails | Transparent images now get RGBA WebP thumbnails, but ones imported before that keep black backgrounds until re-imported. A maintenance job would re-run `write_thumbnails` from the original, update `thumbnail_key` (`.jpg` → `.webp`), delete the old files, and redo colours and pHash. [storage.md](storage.md) | Medium |
| Possible-duplicate (pHash) flags | Hashes are stored; flags and report UI not built. Must suppress gridded/gridless siblings. [ingestion.md](ingestion.md) | Low |
| `api_host` defaults to 0.0.0.0 | Only `python -m backend.app.main` uses it (Electron forces 127.0.0.1; Docker passes `--host`). Default to loopback, then drop the `# nosec B104`. | Low |
| Storage lock on filesystems without locking | The data-dir lock runs unguarded (with a warning) where `flock`/`msvcrt` isn't supported, e.g. some network shares. | Low |
| Unbounded graceful shutdown | Set uvicorn `timeout_graceful_shutdown` so a streaming ZIP export or upload can't hold shutdown open. | Low |
| Purge and backup can't stop part-way | Library purge and `backup_database` ignore the shutdown signal; make them resumable or atomic first. | Low |
| `PermissionError` at commit classified `file` | On Windows, antivirus can briefly lock a file during the rename; consider `transient` at stage `db_save`. | Low |
| Removing tag packs | Packs are opt-in since first boot seeds only `common`, but can't be removed. | Low |
| Shared `ModelCard` | Model cards are duplicated in `ModelStep` (setup wizard) and `SettingsTabContent`. | Low |
| E2E first run on a clean machine | The backend can start before the model has downloaded, so the seed import never runs. Download before starting the webServer. | Low |
| Session-based authentication | Until then server mode must sit behind an authenticating reverse proxy. [security.md](security.md) | Medium |
| Drop folder | Server-mode bulk import without the browser: a watched folder whose files are imported, then removed. Local folder import and the linked library are built ([library-setup.md](library-setup.md)). [local-ingest.md](local-ingest.md#9-feature-3-drop-folder-outline) | Low |
| Move library | Settings only repoints folders today; the user moves files by hand. Copy, verify, switch, then remove the old copy. Due before launch (user decision 2026-10-19). | High |
| Backups as a feature | Daily backups exist (SQLite plus a full LanceDB copy into the store) plus a snapshot before migrations, but have no restore and no UI, and copy every model's vectors. Deferred from library setup (2026-10-19); design them on their own. [storage.md](storage.md#backups) | Medium |
| Framework majors | Tailwind 3 → 4 with tailwind-merge 3 (also clears the `braces` audit finding), vitepress 2 once stable (then drop the docs `vite` override). Tailwind 4 needs a visual pass: v4 has no regex `safelist` (tag chip colours) or `<alpha-value>` (the `shade` colour), its CSS theme has no separate text-colour palette (the ink colours), it changes the default border, ring and shadow scales, and needs `tw-animate-css` in place of `tailwindcss-animate`. Dependabot ignores Tailwind 4 and tailwind-merge 3 until then. TypeScript 7 waits on typescript-eslint (supports < 6.1). jscpd 5 is a rewrite that scans a different file set; check its coverage before moving the gate off 4.0.5. | Low |

## Key design constraints

1. Builds on Windows and Linux; runs on Windows, Linux and macOS (Apple Silicon).
2. The three deployment modes behave the same apart from setup and packaging.
3. Server mode has no built-in authentication: it must only be exposed behind a reverse proxy that authenticates users.
4. The embedding model loads in the background and never blocks startup. Without a model, ingest pauses ("No AI model is available") and the web UI shows the setup screen.
5. A bad file fails only that file; system problems pause the import queue instead of failing items.
6. Item state transitions go through `backend/app/services/ingest_state.py`; job status is only written by `recompute_job_status()`.
7. Each embedding model has its own LanceDB table; switching models re-embeds the library.
