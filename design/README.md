# Design Documentation

Architecture and design documentation for Scene Atlas. These documents describe how the system works, the decisions behind it, and what's known to be incomplete.

For how to build, run, test, and deploy, see [docs/development/](../docs/development/).

## System Architecture

How each major subsystem works.

| File | Description |
|------|-------------|
| [backend.md](backend.md) | Backend API server -- FastAPI, services, configuration, endpoints |
| [storage.md](storage.md) | Data storage -- SQLite schema, LanceDB vectors, ImageStore filesystem, backups |
| [concurrency-architecture.md](concurrency-architecture.md) | Concurrency model -- resource guards, threading, async, and locking patterns |
| [electron.md](electron.md) | Electron desktop app -- windows, IPC, sidecar lifecycle, packaging |

## Feature Design

How individual features and subsystems are designed.

| File | Description |
|------|-------------|
| [search.md](search.md) | Search system -- hybrid FTS5 + CLIP semantic, RRF fusion, phrase matching, model selection |
| [frontend.md](frontend.md) | Frontend SPA -- React, components, hooks, filter logic |
| [ingestion.md](ingestion.md) | Ingestion pipeline -- batched processing, CLIP embeddings, background jobs |
| [web-import.md](web-import.md) | Web import flow -- upload, grouping, preview, confirm, processing |
| [parser.md](parser.md) | ImageParser -- filename parsing, tag extraction, image group detection |
| [import-state-machine.md](import-state-machine.md) | Import state machine -- 7 statuses, transitions, frontend mapping (being replaced, see ingest-redesign.md) |
| [ingest-redesign.md](ingest-redesign.md) | **In progress** -- durable per-item ingest pipeline (ADR-018): data model, worker, upload protocol, dedup tiers, implementation plan |
| [group-view.md](group-view.md) | Group view -- hero+mosaic card layout for browsing by image group |
| [tag-packs.md](tag-packs.md) | Tag packs -- genre-specific vocabularies, import mechanics, settings integration |
| [resource-management.md](resource-management.md) | Resource management -- detection, concurrency controls, memory monitoring |
| [dialog-focus-management.md](dialog-focus-management.md) | Focus management across dialog and modal components |
| [hf-model-management.md](hf-model-management.md) | HuggingFace model download, switching, and GPU detection |

## Standards and Decisions

Design decisions, visual standards, and security posture.

| File | Description |
|------|-------------|
| [decisions.md](decisions.md) | **Architecture Decision Log** -- numbered record of all major design decisions (ADRs 001-018) |
| [visual-language.md](visual-language.md) | Visual design system -- tokens, typography, components, patterns |
| [security.md](security.md) | Security evaluation for hosted deployment mode |
| [testing.md](testing.md) | Testing strategy -- CI/CD tiers, coverage targets, test conventions |
| [onnx-int8-quantisation.md](onnx-int8-quantisation.md) | ONNX INT8 quantisation methodology and results |
| [grid-detection-v3.md](grid-detection-v3.md) | Grid detector v3 research: twin-difference labels, held-out results, small-map diagnosis, port recommendation |

## Status and Backlog

What's done, what's in progress, and what's known to be incomplete.

| File | Description |
|------|-------------|
| [status-and-roadmap.md](status-and-roadmap.md) | **Single source of truth** -- feature inventory, in-progress work, backlog |
| [technical-debt.md](technical-debt.md) | Code quality improvements with specific file paths and fix guidance |
| [code-quality-baseline.md](code-quality-baseline.md) | Pre-release quality baseline -- duplication, comments, dead code, types, coverage; comment rubric |

## System Overview

```
+---------------------------------+
|      Electron Main Process      |  (desktop mode only)
|  +-----------+  +------------+  |
|  | Setup     |  | Main       |  |
|  | Window    |  | Window     |  |
|  +-----------+  +------+-----+  |
|                        | IPC    |
+------------------------+--------+
                         |
+------------------------v--------+
|        React Frontend           |
|        (Vite :5173)             |
+----------------+----------------+
                 | HTTP
+----------------v----------------+
|        FastAPI Backend          |
|        (:8000)                  |
+-------+----------+-------------+
        |          |
  +-----v-----+ +-v----------+ +--------------+
  |  SQLite   | |  LanceDB   | |  ImageStore  |
  | (metadata,| | (disk-     | |  (files,     |
  |  tags,    | |  backed    | |  hash-shard) |
  |  FTS5)    | |  vectors)  | +--------------+
  +-----------+ +------------+
```

## Keeping These Docs Updated

Update these documents when:
- A new ADR is added (architecture change)
- A component's interface or behavior changes significantly
- A known gap is resolved
- New components are added

The decision log (`decisions.md`) is append-only -- decisions are never deleted, only superseded by newer decisions that reference the old one.
