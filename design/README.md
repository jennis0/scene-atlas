# Design Documentation

Architecture and design documentation for Scene Atlas. These documents describe how the system works, the decisions behind it, and what's known to be incomplete.

For how to build, run, test, and deploy, see [docs/development/](../docs/development/).

## System Architecture

How each major subsystem works.

| File | Description |
|------|-------------|
| [backend.md](backend.md) | Backend API server -- FastAPI, services, configuration, endpoints |
| [storage.md](storage.md) | Data storage -- SQLite schema, LanceDB vectors, ImageStore filesystem, backups |
| [resource-management.md](resource-management.md) | Concurrency and resources -- prepare pool, heavy-op semaphore, JobRunner, IngestWorker, memory budget, resource-aware defaults |
| [electron.md](electron.md) | Electron desktop app -- windows, IPC, sidecar lifecycle, packaging, GPU builds |
| [gpu-acceleration.md](gpu-acceleration.md) | ONNX Runtime execution providers -- `inference_device`, CUDA / DirectML / CoreML, CPU fallback |

## Feature Design

How individual features and subsystems are designed.

| File | Description |
|------|-------------|
| [search.md](search.md) | Search system -- hybrid FTS5 + CLIP semantic, RRF fusion, phrase matching, model selection |
| [frontend.md](frontend.md) | Frontend SPA -- structure, gallery and search state, grouped view, imports client |
| [editor-metadata-first.md](editor-metadata-first.md) | Plan: group editor loads summaries first and details on demand, bulk edits by id, virtualised All view (with measurements) |
| [ingestion.md](ingestion.md) | Ingestion pipeline (ADR-018) -- import data model, item state machine, upload protocol, ingest worker, duplicate tiers, stored format, maintenance, recovery |
| [local-ingest.md](local-ingest.md) | Plan: local folder import (desktop app), linked library in place, drop folder |
| [parser.md](parser.md) | ImageParser -- filename parsing, tag extraction, image group detection |
| [tag-packs.md](tag-packs.md) | Tag packs -- genre-specific vocabularies, import mechanics, settings integration |
| [dialog-focus-management.md](dialog-focus-management.md) | Focus management across dialog and modal components |
| [hf-model-management.md](hf-model-management.md) | Hugging Face model download, switching and first-boot setup |

## Standards and Decisions

Design decisions, visual standards, and security posture.

| File | Description |
|------|-------------|
| [decisions.md](decisions.md) | **Architecture Decision Log** -- numbered record of all major design decisions (ADRs 001-019) |
| [visual-language.md](visual-language.md) | Visual design system -- tokens, typography, components, patterns |
| [security.md](security.md) | Security evaluation for hosted deployment mode |
| [testing.md](testing.md) | Testing strategy -- where checks run, fixtures, test conventions |
| [onnx-int8-quantisation.md](onnx-int8-quantisation.md) | ONNX INT8 quantisation methodology and results |
| [grid-detection-v3.md](grid-detection-v3.md) | Grid detector v3 research: twin-difference labels, held-out results, small-map diagnosis, port recommendation |

## Status and Backlog

What's done, what's in progress, and what's known to be incomplete.

| File | Description |
|------|-------------|
| [status-and-roadmap.md](status-and-roadmap.md) | **Single source of truth** -- feature inventory, in-progress work, backlog (including code-quality items) |
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
|  (Vite :5173 in development)    |
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
