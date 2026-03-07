# Scene Atlas — Status and Roadmap

**Last updated:** 2026-03-07

## What Scene Atlas Does

Scene Atlas is a tool for viewing and searching large collections of tabletop RPG scenes (battlemaps, vistas, portraits, encounter art). Key capabilities:

- **Search**: By name, author, tags, color, grid type, and semantic image description (CLIP-powered)
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
| Grouped search endpoint | `backend/app/api/search.py` (`/groups`), `frontend/src/hooks/useGroupSearch.ts` | Dedicated endpoint with hero+mosaic, infinite scroll |
| Import pipeline | `backend/pipeline/ingestion.py`, `frontend/src/hooks/useImportState.ts` | Batched: prepare → CLIP → DB → Qdrant |
| Group detection | `backend/app/services/image_parser.py` | Two-pass: folder-based + prefix-based |
| Grid detection | `backend/app/services/grid_detector.py` | Automated for battlemaps |
| Tag system | `backend/app/api/tags.py`, `frontend/src/components/TagManagementDialog.tsx` | Categories with aliases, custom colors/icons |
| Color search | `backend/app/services/color_search.py` | Dominant color extraction and filtering |
| Image viewer | `frontend/src/components/ImageViewer.tsx` | Sidebar with metadata, scenes partitioned by subgroup |
| Edit group dialog | `frontend/src/components/EditGroupDialog.tsx` | Drag-and-drop reordering, merge, type toggle |
| Export | `backend/app/api/export.py` | Full library export as ZIP |
| Settings UI | `frontend/src/components/SettingsPanel.tsx`, `backend/app/api/settings.py` | Auto-save on blur, 6 configurable settings |
| Activity dock | `frontend/src/components/ActivityDock.tsx` | Real-time import progress, connection status |
| Video support | Throughout pipeline | First-frame extraction, media_type field |
| ONNX Runtime for CLIP | `backend/app/services/clip_service.py` | FP16 models, ~289 MB (was ~500 MB with PyTorch) |
| Electron desktop app | `electron/src/main.ts` | Sidecar lifecycle, borderless titlebar, config storage |
| Backup system | `backend/pipeline/maintenance.py` | Automated daily backups with weekly rotation |
| Duplicate detection | `frontend/src/hooks/useImportUpload.ts` | SHA-256 hash check before upload |
| Import robustness | `backend/app/services/import_state.py` | `broken` status on crash, `/fail` endpoint, cancel with cleanup |
| Concurrency control | `backend/app/services/prepare_pool.py`, `backend/app/api/dependencies.py` | Global executor pool, admission control semaphore, resource-aware defaults |

### In Progress (On Branches)

| Feature | Branch | Plan File | Status |
|---------|--------|-----------|--------|
| Security Phase 2 | `feature/security-phase-2` (unpushed) | `docs/plans/2026-03-03-security-phase-2.md` | Auth middleware, rate limiting, security headers, CI scanning — all implemented but branch not pushed. Developer on leave. |

### Planned (Not Started)

| Feature | Plan File | Priority | Summary |
|---------|-----------|----------|---------|
| Remove import confirmation | `docs/plans/2026-03-05-remove-import-confirmation.md` | High | Simplify state machine by removing confirmation/review layer. 10 tasks covering backend migration, API simplification, frontend cleanup. |
| Live import review | `docs/plans/2026-03-02-live-import-review.md` + `design` variant | Medium | Edit groups in EditGroupDialog while import is still processing. Pending groups shown as spinner stubs. |
| Adaptive memory concurrency | `docs/plans/2026-03-02-adaptive-memory-concurrency-design.md` | Medium | Use psutil to dynamically adjust worker count based on available RAM per batch. Prevents OOM on constrained hardware. |
| Ingest error reporting UI (Stage 3) | `docs/plans/2026-03-05-ingest-error-reporting-stage3.md` | Medium | Frontend UI for displaying import errors/warnings. ImportDetailsDialog, activity dock indicators. Backend data layer already complete. |

### Backlog Items

| Item | Tracked In | Priority |
|------|-----------|----------|
| E2E test expansion (85 remaining tests) | `design/e2e-todo.md` | P1-P3 |
| Code quality improvements (8 items) | `design/code-quality-backlog.md` | Medium |
| Filename in analyse errors | `design/upload-error-improvements-todo.md` | Low |
| Major ecosystem upgrades (Tailwind 4, ESLint 10, React 19, React Router 7) | `design/frontend-hardening-handover.md` (Priority 3) | Low |

---

## Architecture Quick Reference

- **Backend**: FastAPI + SQLite + Qdrant (embedded) + ONNX Runtime CLIP
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + Radix UI + React Query
- **Desktop**: Electron with PyInstaller sidecar
- **Pipeline**: Batched ingestion (prepare → CLIP → DB → Qdrant) via in-process JobRunner
- **Search**: Dual endpoints — flat `/search` and grouped `/search/groups` with RRF ranking
- **State machine**: 7 import states (uploading → staging → active → completed/failed/cancelled/expired/broken)

For detailed architecture, see:
- [backend.md](backend.md) — API endpoints, services, config
- [frontend.md](frontend.md) — Components, hooks, patterns
- [storage.md](storage.md) — Database schema, Qdrant, file storage
- [ingestion.md](ingestion.md) — Pipeline architecture
- [decisions.md](decisions.md) — All Architecture Decision Records (ADRs 001-015)

---

## Key Design Constraints

1. Must build and run on Windows, Linux, and macOS
2. Three deployment modes must behave identically (Electron, server, dev)
3. When `AUTH_TOKEN` is not configured, app must behave as before (backwards compat)
4. CLIP model loaded in background — doesn't block startup
5. Per-image error isolation — one bad image doesn't fail the batch
6. All state changes go through `transition_job_status()` for consistency
