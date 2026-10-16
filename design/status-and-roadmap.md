# Scene Atlas — Status and Roadmap

**Last updated:** 2026-10-16

## What Scene Atlas Does

Scene Atlas is a tool for viewing and searching large collections of tabletop RPG scenes (battlemaps, vistas, portraits, encounter art). Key capabilities:

- **Search**: By name, author, tags, color, grid type, and semantic image description (CLIP/SigLIP2-powered)
- **Import**: Drag-and-drop upload with automatic group detection, duplicate checking, and type-aware processing
- **Groups**: Related images grouped together (e.g., seasonal variants of same map). Groups display as hero+mosaic cards
- **Type-aware processing**: Battlemaps get grid detection; scenes skip it
- **Three deployment modes**: Electron desktop app, web server behind reverse proxy, developer mode

---

## Feature Status

### Core Features (Complete)

| Feature | Key Files | Notes |
|---------|-----------|-------|
| Image search (text + semantic) | `backend/app/api/search.py`, `frontend/src/hooks/useGallerySearch.ts` | FTS5 + CLIP with RRF ranking |
| FTS phrase matching | `backend/app/services/fts_service.py` | Quoted phrases (`"forest shrine"`) use FTS5 native adjacent-word matching; excluded from alias expansion |
| Grouped search endpoint | `backend/app/api/search.py` (`/groups`), `frontend/src/hooks/useGroupSearch.ts` | Dedicated endpoint with hero+mosaic, infinite scroll |
| Import pipeline (ADR-018) | `backend/pipeline/ingest_*.py`, `backend/app/api/imports.py`, `frontend/src/lib/import/` | Durable per-file items; dedicated ingest worker; resumable per-file upload; crash recovery. See [ingestion.md](ingestion.md) |
| Group detection | `backend/app/services/image_parser.py` | Two-pass: folder-based + prefix-based |
| Grid detection (ADR-019) | `backend/app/services/grid/`, `backend/app/services/grid_detector.py` | v3 spectral detector with ONNX classifiers for maps ≥1000 px, legacy detector below; `grid_source` records filename/detector/user |
| Tag system | `backend/app/api/tags.py`, `frontend/src/components/TagManagementDialog.tsx` | Categories with aliases, custom colors/icons |
| Color search | `backend/app/services/color_search.py` | Dominant color extraction and filtering |
| Image viewer | `frontend/src/components/ImageViewer.tsx` | Sidebar with metadata, scenes partitioned by subgroup |
| Edit group dialog | `frontend/src/components/EditGroupDialog.tsx` | Drag-and-drop reordering, merge, type toggle |
| Export | `backend/app/api/export.py` | Full library export as ZIP |
| Settings UI | `frontend/src/components/SettingsPanel.tsx`, `backend/app/api/settings.py` | Auto-save on blur, 6 configurable settings |
| Import UI | `frontend/src/components/imports/`, `frontend/src/components/ActivityDock.tsx` | Import dialog with group ledger, activity dock, import report (retry, import as new copy, undo) |
| Video support | Throughout pipeline | First-frame extraction, media_type field |
| Multi-model ONNX inference | `backend/app/services/clip_service.py`, `backend/app/services/model_registry.py` | HF-hosted model registry; CLIP ViT-B/32 (512d), SigLIP2-Base (768d), SigLIP2-SO400M (1152d); FP16 ONNX; SentencePiece tokenizer support |
| HuggingFace model download & management | `backend/app/services/model_registry.py`, `backend/app/services/model_download_service.py`, `backend/app/api/models.py`, `frontend/src/components/setup/ModelSetupScreen.tsx` | HF-hosted ONNX downloads to APP_DATA_DIR/models/; atomic download with version.json completion marker; POST /active switches model + triggers re-embed; first-boot overlay (web mode); AI Model settings section |
| GPU acceleration | `backend/app/services/clip_service.py` | CUDA → DirectML → CoreML → CPU provider chain; DirectML session recreation on failure, CPU fallback |
| Electron desktop app | `electron/src/main.ts` | Sidecar lifecycle, borderless titlebar, config storage |
| Backup system | `backend/pipeline/maintenance.py` | Automated daily backups with weekly rotation |
| Duplicate detection | `backend/pipeline/image_hashes.py`, `frontend/src/lib/import/hash.worker.ts` | Byte hash (client and server) and decoded-pixel hash auto-skip; pHash stored |
| Storage format | `backend/pipeline/stored_format.py` | Optional WebP/JPEG/PNG conversion of new imports; off by default |
| Concurrency control | `backend/app/services/prepare_pool.py`, `backend/app/api/dependencies.py` | Global executor pool, admission control semaphore, resource-aware defaults |
| Memory-aware concurrency | `backend/app/resource_detector.py` | psutil-based defaults at first boot; 500 MB per worker, 2 GB reserve |
| Automated labelling | `scripts/labelling/` | Sampling, grid labelling, three-description format, UUID anonymization, quality guardrails |
| CI hardening | `.github/workflows/ci.yml`, `.husky/pre-push` | Pre-push hook; unit tests on Ubuntu + Windows + macOS; integration tests on PRs; Dependabot |
| E2E test infrastructure | `e2e/` | Real encrypted fixture images (Git LFS); reusable action helpers; seeds through the import API |
| Stress tests | `stress_tests/` | Import protocol under load, concurrency and failure; see `docs/development/stress-testing.md` |

### In Progress (On Branches)

| Feature | Branch | Plan File | Status |
|---------|--------|-----------|--------|
| Ingest phase 5-6: storage format, E2E/stress tests on the new API, docs | `feature/ingest-phase6` | [ingestion.md](ingestion.md) | In review |
| Security Phase 2 (headers + rate limiting) | `feature/security-phase-2-headers` | [security.md](security.md) | Security headers, rate limiting (8 endpoints), CI scanning, CORS warning. Auth deferred to Phase 3. |

### Backlog Items

| Item | Tracked In | Priority |
|------|-----------|----------|
| Session-based auth (Phase 3) | [security.md](security.md) | High |
| Bulk import of an existing local library (linked folders) | [ingestion.md](ingestion.md) §14 | High |
| Possible-duplicate (pHash) flags in the import report | [ingestion.md](ingestion.md) §12 | Medium |
| E2E test expansion (~31 remaining tests) | [e2e-todo.md](e2e-todo.md) | P1-P3 |
| Code quality improvements (7 items) | [technical-debt.md](technical-debt.md) | Medium |
| Real LanceDB in integration tests | — | Low |
| Tailwind CSS 3 → 4 (requires tailwind-merge v2→v3) | — | Low |
| ESLint 8 → 10 (flat config migration) | — | Low |
| React 18 → 19 (blocked by @dnd-kit compatibility) | — | Low |
| React Router 6 → 7 (low risk, only one route) | — | Low |
| lucide-react 0.307 → 0.577 (icon renames) | — | Low |
| Electron session-level CSP narrowing | — | Low |
| GitHub Actions Node.js 26 upgrade | — | Medium (deadline: 2027-04-30) |

---

## Architecture Quick Reference

- **Backend**: FastAPI + SQLite + LanceDB (disk-backed) + ONNX Runtime (CLIP / SigLIP2)
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + Radix UI + React Query
- **Desktop**: Electron with PyInstaller sidecar
- **Pipeline**: Dedicated `IngestWorker` claims durable import items in batches (prepare → embed → one SQLite commit → LanceDB); JobRunner handles maintenance, backfills and rebuilds
- **Search**: Dual endpoints — flat `/search` and grouped `/search/groups` with RRF ranking; hybrid FTS5 + semantic + alias expansion
- **Import state**: per item (`awaiting_bytes` → `ready` → `processing` → `done`/`duplicate`/`failed`/`skipped`); jobs are `active`/`paused`/`completed`/`cancelled` and derived from item counts. Jobs never fail as a whole.

For detailed architecture, see:
- [backend.md](backend.md) — API endpoints, services, config
- [frontend.md](frontend.md) — Components, hooks, patterns
- [storage.md](storage.md) — Database schema, LanceDB, file storage
- [ingestion.md](ingestion.md) — Import pipeline: data model, worker, upload protocol, duplicates, UI
- [search.md](search.md) — Search architecture (FTS5, semantic, RRF, phrase matching, multi-model)
- [gpu-acceleration.md](gpu-acceleration.md) — GPU provider chain, DirectML maintenance notes
- [decisions.md](decisions.md) — All Architecture Decision Records (ADRs 001-019)

---

## Key Design Constraints

1. Must build and run on Windows, Linux, and macOS
2. Three deployment modes must behave identically (Electron, server, dev)
3. When `AUTH_TOKEN` is not configured, app must behave as before (backwards compat)
4. CLIP model loaded in background — doesn't block startup; if no model has been downloaded yet the service enters an error state and the frontend blocks with a setup screen until a model is selected and downloaded
5. Per-image error isolation — one bad image doesn't fail the batch
6. Import item transitions follow `ingest_state.py`; job status is only ever derived by `recompute_job_status()`
7. Switching embedding models creates a new LanceDB table — run `rebuild_all_embeddings()` after model changes
