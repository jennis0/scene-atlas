# Architecture Decision Log

This document records all significant architectural decisions for the Scene Atlas project. Each decision is numbered, dated, and includes context, the decision itself, and consequences.

---

## ADR-001: Hash-sharded filesystem for image storage

**Date:** 2025-01 (initial design)
**Status:** Accepted

**Context:** We need to store potentially 100k+ images. Storing them flat in one directory causes filesystem performance degradation. We also want the option to migrate to S3/MinIO later.

**Decision:** Use an `ImageStore` abstraction with a hash-sharded directory layout: `base_dir/ab/cd/abcdef1234.jpg`. Images are keyed by UUID, not by author/path. The DB stores `storage_key` and `thumbnail_key` referencing the store — never raw filesystem paths.

**Consequences:**
- Max ~256 entries per shard directory; scales to O(100k+) images
- Decouples logical metadata (author, tags) from physical storage
- All file serving goes through API endpoints, not static mounts
- Storage interface (`put`, `get_path`, `delete`, `exists`) is swappable to S3 later
- Deleting an image from the DB doesn't automatically clean up the store (must call `ImageStore.delete`)

---

## ADR-002: SQLite for relational data, Qdrant for vectors

**Date:** 2025-01 (initial design)
**Status:** Accepted

**Context:** We need relational storage for images, tags, variant groups, and import jobs. We also need similarity search over CLIP embeddings.

**Decision:** Use SQLite (via SQLAlchemy) for all relational data and Qdrant for vector embeddings. They are separate stores with `image_id` as the join key.

**Consequences:**
- SQLite is zero-config, single-file, good enough for a single-user desktop tool
- Qdrant runs as a Docker container alongside the Prefect infrastructure
- Semantic search queries Qdrant first (returns image IDs), then hydrates from SQLite
- If Qdrant is down, text/filter search still works; only semantic search degrades

---

## ADR-003: Prefect for flow orchestration

**Date:** 2025-01 (initial design)
**Status:** Accepted

**Context:** Image ingestion is a multi-step pipeline (parse metadata, copy to store, generate thumbnails, extract colors, generate CLIP embeddings, save to DB, save to Qdrant). We need observability, retries, and async execution.

**Decision:** Use Prefect 3 with a Docker-hosted server (Postgres + Redis backend). Flows are defined in `backend/flows/` and can be run directly (for dev/CLI) or submitted as deployments (for async execution via workers).

**Consequences:**
- `process_single_image` is a Prefect `@flow`; sub-steps are `@task`s with retry support
- Prefect server provides a UI at `localhost:4200` for monitoring flow runs
- The `ImportJob` model has a `flow_run_id` field for linking to Prefect tracking
- Docker Compose runs: Prefect server, Prefect services, Prefect worker, Postgres, Redis, Qdrant
- Web import processing uses Prefect deployments for both analysis and processing (see ADR-007)
- Worker runs locally (not in Docker) for filesystem and dependency access

---

## ADR-004: CLIP ViT-B/32 for semantic search

**Date:** 2025-01 (initial design)
**Status:** Accepted

**Context:** We want users to search battlemaps by visual/semantic description (e.g. "dark forest with river").

**Decision:** Use OpenAI's CLIP ViT-B/32 model (via HuggingFace transformers). Images are encoded to 512-dim vectors at ingest time; text queries are encoded at search time. Both project into the same embedding space.

**Consequences:**
- Model is ~600MB, loaded once at startup (lazy singleton via `get_clip_service()`)
- Runs on CPU by default; `clip_device` setting supports CUDA
- Each image ingest generates one embedding; stored in Qdrant
- Cosine similarity is used for matching (configured in Qdrant collection)

---

## ADR-005: DB-driven tag vocabulary with alias support

**Date:** 2025-01
**Status:** Accepted

**Context:** We need to extract meaningful tags from battlemap filenames. Hardcoded tag patterns are brittle and hard to extend.

**Decision:** Tag categories and their vocabularies are stored in the `TagCategory` table and seeded at startup. Each entry can be a plain string or an object with aliases: `{"value": "rain", "aliases": ["rainy", "raining"]}`. The `BattlemapParser` loads these from DB to build its vocabulary lookup.

**Consequences:**
- Adding new tag words only requires updating the seed data (or eventually a UI)
- Aliases resolve to canonical values (e.g. "rainy" → "rain")
- Tags are categorized (lighting, season, weather, terrain, etc.) enabling faceted filtering
- Filter logic: OR within same category, AND across categories

---

## ADR-006: Variant group detection — two-pass approach

**Date:** 2025-02
**Status:** Accepted

**Context:** Battlemaps are often distributed as variant groups (same map, different lighting/weather/grid). We need to detect groups from folder structure and/or filename prefixes. Folder hierarchies vary widely across different map creators.

**Decision:** Use a two-pass approach in `BattlemapParser.group_files()`:

1. **Folder-based detection (pass 1):** The parser checks if the path has enough depth (3+ parts) and assigns a `group_from_folder` flag. After pass 1, a merge step detects when the top-level folder is actually the variant group (not the author) — signalled by a subfolder name matching the top folder.

2. **Prefix-based merging (pass 2):** For files where the parser couldn't find a group folder, files are sorted alphabetically and merged by common filename prefix (minimum 6 chars, trimmed to word boundaries). Merging only happens within the same parent folder.

**Author inference:**
- Folder-based group found → author is the folder above the group folder
- No group folder found → author is the top-level folder in the relative path
- All intermediate folders are generic → top folder IS the group, author is unknown
- Flat files (no folders) → author is unknown (user fills in during import)

**Consequences:**
- Handles common structures: `author/group/file`, `group/subvariant/file`, `group/generic/generic/file`
- Generic folders (resolution, grid, format names) are skipped when searching for the group folder
- The merge step correctly combines `GroupName 30x30/Eerie/{files}` + `GroupName 30x30/Abandoned Campsite/{files}` into one group
- When author can't be inferred, it's `None` and the user provides it during import preview

---

## ADR-007: Web import uses Prefect deployments for all processing

**Date:** 2025-02
**Status:** Accepted (implemented)

**Context:** The web import needs two data processing phases: (1) analysing uploaded files to detect variant groups, and (2) processing confirmed groups through the full ingestion pipeline. Both should be orchestrated through Prefect for observability, retries, and scalability. The analysis step may grow to include heavyweight compute (AV scanning, AI metadata extraction) in future.

**Decision:** Two Prefect deployments handle web import processing:

1. **`analyse_upload`** — Called synchronously by the upload endpoint (`run_deployment(timeout=120)`). Parses and groups files via `BattlemapParser.group_files()`. Uses `persist_result=True` so the API process can retrieve results from the worker.

2. **`process_import_group`** — Called async by the confirm endpoint (`run_deployment(timeout=0)`). Processes each file via `process_single_image` subflow. Updates `ImportJob` progress counters after each image. The `flow_run_id` is stored on the `ImportJob` for tracking.

The worker runs **locally** (not in Docker) because it needs project code, Python dependencies (CLIP, PIL, scikit-learn), and filesystem access. Docker Compose provides only infrastructure (Prefect server, Postgres, Redis).

**Consequences:**
- All data processing is visible in the Prefect UI at localhost:4200
- Retry support from Prefect on all tasks
- `ImportJob.flow_run_id` links to the Prefect flow run
- Upload has ~2-5s additional latency (worker polling + subprocess startup) for the analysis step
- Requires: Docker infrastructure running, deployments registered, local worker running
- The `ThreadPoolExecutor` and `_process_group_sync` from imports.py have been removed
- All flow/task parameters use primitive types (str, dict, list) for JSON serialization

---

## ADR-008: Frontend architecture — React + Vite + Tailwind

**Date:** 2025-01 (initial design)
**Status:** Accepted

**Context:** Need a responsive gallery UI with filtering, search, and image viewing.

**Decision:** React 18 + TypeScript + Vite + Tailwind CSS + Radix UI primitives. State management via React Query for server state and `useState` for UI state. API calls via axios.

**Consequences:**
- Vite dev server at `:5173` proxies `/api` to FastAPI at `:8000`
- Radix provides accessible dialog, sheet, checkbox primitives
- React Query handles caching, refetching, and loading states
- `paramsSerializer: { indexes: null }` on axios for FastAPI array param compatibility
- No global state store (Redux/Zustand) — React Query + local state is sufficient for current scope

---

## ADR-009: Image serving through API, not static mounts

**Date:** 2025-01
**Status:** Accepted

**Context:** Images are stored in a hash-sharded directory. We could either mount the store directory as a static path or serve files through API endpoints.

**Decision:** Serve all images through API endpoints: `/images/{id}/file` and `/images/{id}/thumbnail`. No static file mounts.

**Consequences:**
- Frontend uses `api.getImageUrl(id)` / `api.getThumbnailUrl(id)` — never constructs filesystem paths
- Access control can be added later without changing the frontend
- Slightly more overhead per request (DB lookup + FileResponse) but negligible for a local tool
- Vite proxy handles the routing in development

---

## ADR-010: Backup strategy and database migrations

**Date:** 2026-02
**Status:** Accepted

**Context:** The application stores irreplaceable user data (battlemap metadata, tags, variant groups, CLIP embeddings) across three stores: SQLite, the hash-sharded filesystem, and Qdrant. With no backup strategy, a disk failure or an accidental `reset_database.py` run means total data loss. Additionally, the original `init_db()` function used ad-hoc hand-rolled `ALTER TABLE` statements with no version tracking, making schema evolution fragile and difficult to reason about.

**Decision:** Two separate concerns addressed together:

1. **Backups via Prefect flows**: A `backup_database` flow in `backend/flows/maintenance.py` creates a consistent SQLite snapshot (using the `sqlite3.backup()` API, not file copy) and a Qdrant snapshot (via REST API). It rotates old backups: keep last 7 daily + 4 weekly. Registered as a scheduled Prefect deployment running daily at 03:00 UTC. A companion `cleanup_staging` flow removes stale import staging directories (>24h old) every 6 hours. Both flows are observable and manually triggerable via the Prefect UI.

2. **Alembic for schema migrations**: The hand-rolled migration code in `init_db()` is replaced with Alembic. A single initial migration (`001_initial_schema.py`) captures the complete current schema including FTS5 virtual table and triggers. `init_db()` now detects whether the database is fresh (runs all migrations), pre-Alembic (stamps at head), or already Alembic-managed (runs pending migrations). Future schema changes are added as numbered Alembic migration files.

**Consequences:**
- Backups: daily snapshots with rotation; restore procedure documented in tests (`test_backup_restore.py` proves the backup is restorable)
- Staging cleanup: disk space no longer leaks from crashed or abandoned imports
- Alembic: schema changes are versioned, reviewable, and revertable; `alembic upgrade head` is the canonical way to apply migrations
- The `alembic.ini` at project root allows CLI use: `uv run alembic upgrade head`
- Image store files are not backed up by the script — they are large, append-only blobs and the originals typically exist elsewhere; document this assumption
- Qdrant embeddings can be regenerated from images via `write_new_embeddings` flow if the Qdrant snapshot is unavailable
