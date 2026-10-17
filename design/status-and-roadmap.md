# Scene Atlas: Status and Roadmap

**Last updated:** 2026-10-17

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
| Colour search | `backend/app/services/color_search.py` | In-memory numpy index over dominant colours |
| Import pipeline | `backend/app/api/imports.py`, `backend/pipeline/ingest_*.py`, `frontend/src/lib/import/`, `frontend/src/components/imports/` | Durable per-item queue with a dedicated worker (ADR-018). [ingestion.md](ingestion.md) |
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
| Multi-model ONNX inference | `backend/app/services/clip_service.py`, `backend/app/services/model_registry.py` | Small (CLIP ViT-B/32, 512-d), medium (SigLIP2-base, 768-d), large (SigLIP2-so400m, 1152-d). [onnx-int8-quantisation.md](onnx-int8-quantisation.md) |
| Model download and switching | `backend/app/services/model_download_service.py`, `backend/app/api/models.py`, `frontend/src/components/setup/ModelSetupScreen.tsx` | Hugging Face-hosted ONNX; switch pauses ingest and re-embeds. [hf-model-management.md](hf-model-management.md) |
| GPU acceleration | `backend/app/services/ort_providers.py`, `clip_service.py` | `inference_device=auto`; CUDA / DirectML / CoreML / CPU. [gpu-acceleration.md](gpu-acceleration.md) |
| Electron desktop app | `electron/src/`, `backend/pyinstaller/` | Sidecar lifecycle, storage-folder setup. No built-in auto-updater. [electron.md](electron.md) |
| Maintenance | `backend/app/services/scheduler.py`, `backend/pipeline/maintenance.py`, `ingest_maintenance.py`, `vector_reconcile.py` | Daily backups, 6-hourly ingest cleanup, orphan sweep, vector reconciliation |
| Concurrency control | `backend/app/services/prepare_pool.py`, `memory_budget.py`, `api/dependencies.py` | [resource-management.md](resource-management.md) |
| Security hardening | `backend/app/main.py` (`SecurityHeadersMiddleware`), `backend/app/api/rate_limits.py` | Security headers, rate limits, CORS warning. No built-in authentication. [security.md](security.md) |
| Checks | `.husky/pre-push`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` | Lint + unit tests pre-push; security, integration and frontend build on PRs; manual release with cross-platform tests, E2E and builds. [testing.md](testing.md) |
| Release builds | `.github/workflows/release.yml`, `scripts/build/` | Windows x64 (DirectML), macOS arm64, Linux x64 |

## In progress

| Work | Where | Notes |
|---|---|---|
| Pre-release code-quality pass | PR #4 (`chore/pre-release-quality`) | [code-quality-baseline.md](code-quality-baseline.md) |

## Backlog

| Item | Notes | Priority |
|---|---|---|
| Security scans don't fail CI | `continue-on-error: true` on `pip-audit` and `bandit` in `ci.yml`; the target date (2026-03-28) has passed. Triage findings, add targeted exclusions, remove the flag. | Medium |
| GitHub Actions on Node-20-era major versions | `actions/checkout@v4`, `setup-node@v4`, `setup-python@v5`, `astral-sh/setup-uv@v4`, `upload-artifact@v4`, `cache@v4`, `upload-pages-artifact@v3`. Upgrade to the Node 24 majors and re-test each job. | Medium |
| int8 model export depends on untracked code | `scripts/models/export_model_onnx.py` imports `scripts.quantisation.*`, which is gitignored and absent from a clean checkout. [onnx-int8-quantisation.md](onnx-int8-quantisation.md) | Medium |
| Electron sidecar parent-death watchdog | If Electron dies without stopping the sidecar, the backend keeps running. Add a stdin-EOF (or parent-PID) watchdog in `backend/pyinstaller/entry.py`. | Medium |
| Finish the pipeline DB session helper | `backend/pipeline/db.py:pipeline_db` exists and is used by `maintenance.py` and `vector_reconcile.py`; about 15 call sites (`reparse_names`, `retag_all_images`, `backfill_*`, `export_library`, `fix_orphaned_images`, `write_new_embeddings`, `pipeline_config`) still build sessions directly. | Low |
| Possible-duplicate (pHash) flags | Hashes are stored; flags and report UI not built. Must suppress gridded/gridless siblings. [ingestion.md](ingestion.md) | Low |
| Rate limits behind a reverse proxy | slowapi keys on `get_remote_address`, which is the proxy's address once server mode sits behind one, so all clients share one bucket. Enable uvicorn proxy headers with a trusted `FORWARDED_ALLOW_IPS` and document it. | Medium |
| Mislabelled "Concurrent imports" setting | It controls `max_concurrent_prepare` (images prepared in parallel), not simultaneous import jobs as its description says. Relabel or rework. | Low |
| Tag-pack wizard rough edges | First boot seeds every pack, so the wizard shows all as imported; it ignores per-pack `errors` in the `import-multiple` response; that endpoint has no rate limit. | Low |
| Long jobs block shutdown | `JobRunner.shutting_down` is never checked by job functions. | Low |
| Unused / ineffective settings | `max_image_size`, `vector_collection_name` (only a default), `embedding_model` unused; `DATABASE_URL` and path overrides are recomputed in `Settings.__init__`; `max_import_file_size` default differs between schema (2000 MiB) and seed (2048 MiB). | Low |
| Setup page fetches Google Fonts | `electron/setup.html` needs the network on first run for fonts; bundling them would allow a stricter CSP. | Low |
| Deferred frontend extractions | EditGroupDialog / ImageViewer subcomponents, `useSceneFilters`, unifying ImageViewer filtering with `fileFilter.ts`, shared `TagChip` / `PanelHeader` / `ModelCard`, moving confirm flags out of `useEditGroupOperations`. Add component tests first (coverage is low for these). | Low |
| Ingest error classification | A `FileNotFoundError` while placing files at commit (`_place`, stage `db_save`) is classified `file`, failing the batch permanently instead of retrying. `backend/pipeline/error_classifier.py` | Medium |
| No single-backend guard per data dir | Two backends on one `APP_DATA_DIR` corrupt each other's in-flight ingest (`recover()` clears `.incoming/`). Electron has a single-instance lock; standalone/server mode has none. Add a lock file in `APP_DATA_DIR`. | Low |
| E2E can run against a developer's backend | Locally, Playwright reuses an already-running backend on :8000 (`reuseExistingServer`), so a dev backend's real data dir would be used. Start the E2E backend on its own port. `e2e/playwright.config.ts` | Medium |
| ColorIndex loads the whole `colors` table | `color_search.ColorIndex` reloads every colour row into memory on each TTL expiry. Chosen fix: store precomputed LAB columns per colour row and search with a SQL distance query, removing the in-memory index. | Low |
| `SCENE_ATLAS_READY` printed before the socket is bound | Printed from the lifespan; clients must poll `/health` (Electron and the stress runner do). | Low |
| Session-based authentication | Until then server mode must sit behind an authenticating reverse proxy. [security.md](security.md) | Medium |
| Bulk import of a local library | Linked folders read in place, feeding the same item queue. [ingestion.md](ingestion.md) | Low |
| Real LanceDB in integration tests | Tests mock `get_lancedb_service()` | Low |
| Dependency upgrades | Tailwind 3 → 4 (needs tailwind-merge v3), ESLint flat config, React 19 (blocked by @dnd-kit), React Router 7, lucide-react | Low |

## Key design constraints

1. Builds on Windows and Linux; runs on Windows, Linux and macOS (Apple Silicon).
2. The three deployment modes behave the same apart from setup and packaging.
3. Server mode has no built-in authentication: it must only be exposed behind a reverse proxy that authenticates users.
4. The embedding model loads in the background and never blocks startup. Without a model, ingest pauses ("No AI model is available") and the web UI shows the setup screen.
5. A bad file fails only that file; system problems pause the import queue instead of failing items.
6. Item state transitions go through `backend/app/services/ingest_state.py`; job status is only written by `recompute_job_status()`.
7. Each embedding model has its own LanceDB table; switching models re-embeds the library.
