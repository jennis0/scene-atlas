# Design Documentation

Architecture and design documentation for the Scene Atlas project. These documents describe how each component works, the intent behind design choices, and known gaps.

## Documents

| File | Description |
|------|-------------|
| [decisions.md](decisions.md) | **Architecture Decision Log** — numbered record of all major design decisions |
| [backend.md](backend.md) | Backend API server — FastAPI, services, configuration, endpoints |
| [frontend.md](frontend.md) | Frontend SPA — React, components, hooks, filter logic |
| [electron.md](electron.md) | Electron desktop app — windows, IPC, sidecar lifecycle, packaging |
| [storage.md](storage.md) | Data storage — SQLite schema, Qdrant vectors, ImageStore filesystem, backups |
| [testing.md](testing.md) | Testing strategy — CI/CD tiers, coverage targets, test patterns |
| [ingestion.md](ingestion.md) | Ingestion pipeline — batched processing, CLIP embeddings, background jobs |
| [web-import.md](web-import.md) | Web import flow — upload, grouping, preview, confirm, processing |
| [parser.md](parser.md) | ImageParser — filename parsing, tag extraction, image group detection |
| [import-state-machine.md](import-state-machine.md) | Import state machine — 8 statuses, transitions, frontend mapping |
| [group-view.md](group-view.md) | Group view — hero+mosaic card layout for browsing by image group |
| [visual-language.md](visual-language.md) | Visual design system — tokens, typography, components, patterns |
| [code-quality-backlog.md](code-quality-backlog.md) | Deferred code quality items from the 2026-03-04 simplify pass |
| [concurrency-architecture.md](concurrency-architecture.md) | Concurrency model — threading, async, and locking patterns |
| [dialog-focus-management.md](dialog-focus-management.md) | Focus management across dialog and modal components |
| [security.md](security.md) | Security evaluation for hosted deployment mode |
| [e2e-todo.md](e2e-todo.md) | E2E test expansion plan |
| [sidecar-onnx-phase2.md](sidecar-onnx-phase2.md) | Historical: ONNX sidecar size reduction plan (implemented as ADR-014) |
| [upload-error-improvements-todo.md](upload-error-improvements-todo.md) | Upload error handling backend improvements |
| [frontend-hardening-handover.md](frontend-hardening-handover.md) | Historical: Frontend hardening Phase 1 analysis |
| [frontend-hardening-p1p2-handover.md](frontend-hardening-p1p2-handover.md) | Frontend hardening Phase 1+2 implementation handover |
| [status-and-roadmap.md](status-and-roadmap.md) | **Single source of truth** — feature inventory, in-progress work, planned work, backlog |

## System Overview

```
┌─────────────────────────────────┐
│      Electron Main Process      │  (desktop mode only)
│  ┌───────────┐  ┌────────────┐  │
│  │ Setup     │  │ Main       │  │
│  │ Window    │  │ Window     │  │
│  └───────────┘  └─────┬──────┘  │
│                       │ IPC     │
└───────────────────────┼─────────┘
                        │
┌───────────────────────▼─────────┐
│        React Frontend           │
│        (Vite :5173)             │
└───────────────┬─────────────────┘
                │ HTTP
┌───────────────▼─────────────────┐
│        FastAPI Backend          │
│        (:8000)                  │
└──────┬──────────┬───────────────┘
       │          │
 ┌─────▼─────┐ ┌─▼──────────┐ ┌──────────────┐
 │  SQLite   │ │  Qdrant    │ │  ImageStore  │
 │ (metadata,│ │ (embedded  │ │  (files,     │
 │  tags,    │ │  vectors)  │ │  hash-shard) │
 │  FTS5)    │ └────────────┘ └──────────────┘
 └───────────┘
```

## Deployment Modes

| Mode | Frontend | Backend | Notes |
|------|----------|---------|-------|
| **Electron app** | Bundled in `frontend/dist/` | PyInstaller sidecar subprocess | For non-technical users. See [electron.md](electron.md) |
| **Web server** | Served by reverse proxy | Uvicorn behind reverse proxy | For power users with remote access |
| **Developer** | `npm run dev` (:5173) | `uv run python scripts/start.py` (:8000) | Hot reload on both |

## Keeping These Docs Updated

These documents should be updated when:
- A new ADR is added (architecture change)
- A component's interface or behavior changes significantly
- A known gap is resolved
- New components are added

The decision log (`decisions.md`) is append-only — decisions are never deleted, only superseded by newer decisions that reference the old one.
