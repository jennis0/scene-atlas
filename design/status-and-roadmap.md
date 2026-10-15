# Scene Atlas — Status and Roadmap

**Last updated:** 2026-03-15

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
| Import pipeline | `backend/pipeline/ingestion.py`, `frontend/src/hooks/useImportState.ts` | Batched: prepare → CLIP → DB → LanceDB |
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
| Multi-model ONNX inference | `backend/app/services/clip_service.py`, `backend/app/services/model_registry.py` | HF-hosted model registry; CLIP ViT-B/32 (512d), SigLIP2-Base (768d), SigLIP2-SO400M (1152d); FP16 ONNX; SentencePiece tokenizer support |
| HuggingFace model download & management | `backend/app/services/model_registry.py`, `backend/app/services/model_download_service.py`, `backend/app/api/models.py`, `frontend/src/components/setup/ModelSetupScreen.tsx` | HF-hosted ONNX downloads to APP_DATA_DIR/models/; atomic download with version.json completion marker; POST /active switches model + triggers re-embed; first-boot overlay (web mode); AI Model settings section |
| GPU acceleration | `backend/app/services/clip_service.py` | CUDA → DirectML → CoreML → CPU provider chain; DirectML session recreation on failure, CPU fallback |
| Electron desktop app | `electron/src/main.ts` | Sidecar lifecycle, borderless titlebar, config storage |
| Backup system | `backend/pipeline/maintenance.py` | Automated daily backups with weekly rotation |
| Duplicate detection | `frontend/src/hooks/useImportUpload.ts` | SHA-256 hash check before upload |
| Import robustness | `backend/app/services/import_state.py` | `broken` status on crash, `/fail` endpoint, cancel with cleanup |
| Concurrency control | `backend/app/services/prepare_pool.py`, `backend/app/api/dependencies.py` | Global executor pool, admission control semaphore, resource-aware defaults |
| Import error reporting UI | `frontend/src/components/ImportSummaryDialog.tsx` | Per-file errors, warnings, skipped files shown in dialog with colored status stripe |
| Live import review | `frontend/src/hooks/useImportProgressPolling.ts`, `EditGroupDialog.tsx` | Edit groups while import is processing; pending groups shown as spinner stubs |
| Simplified import flow | Migration 018 | Removed confirmation/review layer (pending_groups, all_confirmed, needs_review, awaiting_input) |
| Memory-aware concurrency | `backend/app/resource_detector.py` | psutil-based defaults at first boot; 500 MB per worker, 2 GB reserve |
| Automated labelling | `scripts/labelling/` | Sampling, grid labelling, three-description format, UUID anonymization, quality guardrails |
| CI hardening | `.github/workflows/ci.yml`, `.husky/pre-push` | Pre-push hook; unit tests on Ubuntu + Windows + macOS; integration tests on PRs; Dependabot |
| E2E test infrastructure | `e2e/` | Real encrypted fixture images (Git LFS); reusable action helpers; 37 tests across 10 spec files |

### In Progress (On Branches)

| Feature | Branch | Plan File | Status |
|---------|--------|-----------|--------|
| Ingest pipeline redesign (ADR-018) | `worktree-ingest-redesign` | [ingest-redesign.md](ingest-redesign.md) | Design accepted 2026-10-15; implementation phases 0-6 pending |
| Security Phase 2 (headers + rate limiting) | `feature/security-phase-2-headers` | [security.md](security.md) | Security headers, rate limiting (8 endpoints), CI scanning, CORS warning. Auth deferred to Phase 3. |

### Backlog Items

| Item | Tracked In | Priority |
|------|-----------|----------|
| Session-based auth (Phase 3) | [security.md](security.md) | High |
| E2E test expansion (~31 remaining tests) | [e2e-todo.md](e2e-todo.md) | P1-P3 |
| Code quality improvements (11 items) | [technical-debt.md](technical-debt.md) | Medium |
| Filename in analyse-step error responses | — | Low |
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
- **Pipeline**: Batched ingestion (prepare → CLIP → DB → LanceDB) via in-process JobRunner
- **Search**: Dual endpoints — flat `/search` and grouped `/search/groups` with RRF ranking; hybrid FTS5 + semantic + alias expansion
- **State machine**: 7 import states (uploading → staging → active → completed/failed/cancelled/expired/broken). No confirmation step — groups auto-confirm.

For detailed architecture, see:
- [backend.md](backend.md) — API endpoints, services, config
- [frontend.md](frontend.md) — Components, hooks, patterns
- [storage.md](storage.md) — Database schema, LanceDB, file storage
- [ingestion.md](ingestion.md) — Pipeline architecture
- [search.md](search.md) — Search architecture (FTS5, semantic, RRF, phrase matching, multi-model)
- [gpu-acceleration.md](gpu-acceleration.md) — GPU provider chain, DirectML maintenance notes
- [decisions.md](decisions.md) — All Architecture Decision Records (ADRs 001-018)

---

## Key Design Constraints

1. Must build and run on Windows, Linux, and macOS
2. Three deployment modes must behave identically (Electron, server, dev)
3. When `AUTH_TOKEN` is not configured, app must behave as before (backwards compat)
4. CLIP model loaded in background — doesn't block startup; if no model has been downloaded yet the service enters an error state and the frontend blocks with a setup screen until a model is selected and downloaded
5. Per-image error isolation — one bad image doesn't fail the batch
6. All state changes go through `transition_job_status()` for consistency
7. Switching embedding models creates a new LanceDB table — run `rebuild_all_embeddings()` after model changes
