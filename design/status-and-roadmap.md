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
| Multi-model ONNX inference | `backend/app/services/clip_service.py`, `backend/app/services/model_registry.py` | Small (CLIP ViT-B/32, 512-d), medium (SigLIP2-base, 768-d), large (SigLIP2-so400m, 1152-d). [onnx-int8-quantisation.md](onnx-int8-quantisation.md) |
| Model download and switching | `backend/app/services/model_download_service.py`, `backend/app/api/models.py`, `frontend/src/components/setup/ModelStep.tsx` | Hugging Face-hosted ONNX; switch pauses ingest and re-embeds. [hf-model-management.md](hf-model-management.md) |
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
| Tech-debt pass (follow-up to PR #4) | branch `chore/tech-debt` | Clears the previous backlog's debt rows |

## Backlog

| Item | Notes | Priority |
|---|---|---|
| Sidecar size | ~700 MB on disk, ~170 MB compressed. Biggest parts: lancedb + pyarrow 230 MB (brute-force numpy search over vectors in SQLite would do at our scale, but replaces the vector store: needs an ADR), opencv 145 MB (grid v3 and video thumbnails), scipy 66 MB. scikit-learn (14 MB) is only used for k-means in colour extraction. | Medium |
| Verify the sidecar lifecycle on packaged Windows and macOS | Parent-death watchdog (stdin EOF + PID poll), `msvcrt` storage lock and its loading-page message, graceful stop on Windows, storage-change relaunch waiting on the old lock. Tested on Linux only. | Medium |
| Colour threshold default is loose | ΔE 25 reproduces the old HSL 0.35, but a typical map colour matches ~80% of the library and colour-filtered browse is 70–140 ms slower at 56k images than the old in-memory index. ΔE 12–15 is faster and more useful. No UI control (API only). [search.md](search.md) | Medium |
| transformers 5 for `scripts/models` export | Clears 6 accepted pip-audit IDs (dev-only extra). | Medium |
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
| `gpu-dev` torch stuck at 2.6 | The `pytorch-cuda` index is cu124; move to cu126/cu128. | Low |
| Session-based authentication | Until then server mode must sit behind an authenticating reverse proxy. [security.md](security.md) | Medium |
| Bulk import of a local library | Local folder import (desktop app), then linked folders read in place, then a drop folder. [local-ingest.md](local-ingest.md) | High |
| Dependency upgrades | Tailwind 3 → 4 (needs tailwind-merge v3), ESLint flat config, React 19 (blocked by @dnd-kit), React Router 7, vitepress 2, lucide-react. A full in-range frontend refresh breaks `imports.test.tsx` (likely @tanstack/react-virtual). | Low |

## Key design constraints

1. Builds on Windows and Linux; runs on Windows, Linux and macOS (Apple Silicon).
2. The three deployment modes behave the same apart from setup and packaging.
3. Server mode has no built-in authentication: it must only be exposed behind a reverse proxy that authenticates users.
4. The embedding model loads in the background and never blocks startup. Without a model, ingest pauses ("No AI model is available") and the web UI shows the setup screen.
5. A bad file fails only that file; system problems pause the import queue instead of failing items.
6. Item state transitions go through `backend/app/services/ingest_state.py`; job status is only written by `recompute_job_status()`.
7. Each embedding model has its own LanceDB table; switching models re-embeds the library.
