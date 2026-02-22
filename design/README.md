# Design Documentation

Architecture and design documentation for the Scene Atlas project. These documents describe how each component works, the intent behind design choices, and known gaps.

## Documents

| File | Description |
|------|-------------|
| [decisions.md](decisions.md) | **Architecture Decision Log** — numbered record of all major design decisions |
| [backend.md](backend.md) | Backend API server — FastAPI, services, configuration, endpoints |
| [frontend.md](frontend.md) | Frontend SPA — React, components, API client, filter logic |
| [storage.md](storage.md) | Data storage — SQLite schema, Qdrant vectors, ImageStore filesystem |
| [ingestion.md](ingestion.md) | Ingestion pipeline — Prefect flows, processing steps, infrastructure |
| [web-import.md](web-import.md) | Web import flow — upload, grouping, preview, confirm, processing |
| [parser.md](parser.md) | BattlemapParser — filename parsing, tag extraction, variant group detection |

## System Overview

```
┌─────────────────────┐     ┌──────────────────┐
│   React Frontend    │────▶│   FastAPI Backend │
│   (Vite :5173)      │     │   (:8000)         │
└─────────────────────┘     └──────┬───────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
              ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼──────┐
              │  SQLite   │ │  Qdrant   │ │ ImageStore │
              │  (metadata│ │  (vectors)│ │ (files)    │
              │  + tags)  │ │  :6333    │ │ hash-shard │
              └───────────┘ └───────────┘ └────────────┘
                                   │
                            ┌──────▼──────┐
                            │   Prefect   │
                            │   Server    │
                            │   :4200     │
                            │ (Postgres + │
                            │  Redis)     │
                            └─────────────┘
```

## Keeping These Docs Updated

These documents should be updated when:
- A new ADR is added (architecture change)
- A component's interface or behavior changes significantly
- A known gap is resolved
- New components are added

The decision log (`decisions.md`) is append-only — decisions are never deleted, only superseded by newer decisions that reference the old one.
