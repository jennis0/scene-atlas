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

## ADR-002: SQLite for relational data, LanceDB for vectors

**Date:** 2025-01 (initial design)
**Status:** Accepted (migrated from Qdrant to LanceDB, 2026-03)

**Context:** We need relational storage for images, tags, image groups, and import jobs. We also need similarity search over CLIP embeddings.

**Decision:** Use SQLite (via SQLAlchemy) for all relational data and LanceDB for vector embeddings. They are separate stores with `image_id` as the join key. (Originally used Qdrant; migrated to LanceDB for simpler dependency management — LanceDB is a pure Python/Rust library with no separate server process.)

**Consequences:**
- SQLite is zero-config, single-file, good enough for a single-user desktop tool
- LanceDB runs as a disk-backed, memory-mapped local instance (no Docker or server process required)
- Semantic search queries LanceDB first (returns image IDs), then hydrates from SQLite
- If LanceDB is unavailable, text/filter search still works; only semantic search degrades

---

## ADR-003: Prefect for flow orchestration

**Date:** 2025-01 (initial design)
**Status:** Superseded by ADR-012

**Context:** Image ingestion is a multi-step pipeline (parse metadata, copy to store, generate thumbnails, extract colors, generate CLIP embeddings, save to DB, save to vector DB). We need observability, retries, and async execution.

**Decision:** Use Prefect 3 with a Docker-hosted server (Postgres + Redis backend). Flows are defined in `backend/flows/` and can be run directly (for dev/CLI) or submitted as deployments (for async execution via workers).

**Consequences:** *(historical — see ADR-012 for current architecture)*
- `process_single_image` is a Prefect `@flow`; sub-steps are `@task`s with retry support
- Prefect server provides a UI at `localhost:4200` for monitoring flow runs
- Docker Compose runs: Prefect server, Prefect services, Prefect worker, Postgres, Redis, vector DB

---

## ADR-004: CLIP ViT-B/32 for semantic search

**Date:** 2025-01 (initial design)
**Status:** Accepted

**Context:** We want users to search battlemaps by visual/semantic description (e.g. "dark forest with river").

**Decision:** Use OpenAI's CLIP ViT-B/32 model (via HuggingFace transformers). Images are encoded to 512-dim vectors at ingest time; text queries are encoded at search time. Both project into the same embedding space.

**Consequences:**
- **Update:** Model sizes have changed. See ADR-014/016/017 for the current multi-model architecture (250 MB -- 1 GB ONNX files).
- Model is ~600MB, loaded once at startup (lazy singleton via `get_clip_service()`)
- Runs on CPU by default; `inference_device` setting supports GPU acceleration (CUDA, DirectML, CoreML) — see `design/gpu-acceleration.md`
- Each image ingest generates one embedding; stored in LanceDB
- Cosine similarity is used for matching (configured in LanceDB table)

---

## ADR-005: DB-driven tag vocabulary with alias support

**Date:** 2025-01
**Status:** Accepted

**Context:** We need to extract meaningful tags from battlemap filenames. Hardcoded tag patterns are brittle and hard to extend.

**Decision:** Tag categories and their vocabularies are stored in the `TagCategory` table and seeded at startup from a canonical JSON file (`backend/app/data/tag_vocabulary.json`). Each entry can be a plain string or an object with aliases: `{"value": "rain", "aliases": ["rainy", "raining"]}`. The `ImageParser` loads these from DB to build its vocabulary lookup.

**Consequences:**
- Adding new tag words requires updating the JSON vocabulary file (or using the Tag Management UI)
- Aliases resolve to canonical values (e.g. "rainy" → "rain")
- Tags are categorized (lighting, season, weather, environment, features, state, theme, population, perspective, style) enabling faceted filtering
- Filter logic: OR within same category, AND across categories
- Genre packs (Common, Fantasy, Sci-Fi, Cyberpunk, Horror, Historical) allow selective vocabulary import via Settings

---

## ADR-006: Image group detection — two-pass approach

**Date:** 2025-02
**Status:** Accepted

**Context:** Battlemaps are often distributed as image groups (same map, different lighting/weather/grid). We need to detect groups from folder structure and/or filename prefixes. Folder hierarchies vary widely across different map creators.

**Decision:** Use a two-pass approach in `ImageParser.group_files()`:

1. **Folder-based detection (pass 1):** The parser checks if the path has enough depth (3+ parts) and assigns a `group_from_folder` flag. After pass 1, a merge step detects when the top-level folder is actually the image group (not the author) — signalled by a subfolder name matching the top folder.

2. **Prefix-based merging (pass 2):** For files where the parser couldn't find a group folder, files are sorted alphabetically and merged by common filename prefix (minimum 6 chars, trimmed to word boundaries). Merging only happens within the same parent folder.

**Author inference:**
- Folder-based group found → author is the folder above the group folder
- No group folder found → author is the top-level folder in the relative path
- All intermediate folders are generic → top folder IS the group, author is unknown
- Flat files (no folders) → author is unknown (user fills in during import)

**Consequences:**
- Handles common structures: `author/group/file`, `group/subgroup/file`, `group/generic/generic/file`
- Generic folders (resolution, grid, format names) are skipped when searching for the group folder
- The merge step correctly combines `GroupName 30x30/Eerie/{files}` + `GroupName 30x30/Abandoned Campsite/{files}` into one group
- When author can't be inferred, it's `None` and the user provides it during import preview

---

## ADR-007: Web import uses Prefect deployments for all processing

**Date:** 2025-02
**Status:** Superseded by ADR-012

**Context:** The web import needs two data processing phases: (1) analysing uploaded files to detect image groups, and (2) processing confirmed groups through the full ingestion pipeline. Both should be orchestrated through Prefect for observability, retries, and scalability.

**Decision:** Two Prefect deployments handle web import processing: `analyse_upload` (synchronous) and `process_import_group` (async fire-and-forget).

**Consequences:** *(historical — see ADR-012 for current architecture)*
- Prefect provided observability and retry support
- Required Docker infrastructure (Prefect server, Postgres, Redis) plus a local worker
- Added ~2-5s latency to uploads due to worker polling

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
- **Status note (2026-10):** Radix now provides only checkbox, dropdown-menu and popover. Dialogs use a custom portal component (`frontend/src/components/ui/dialog.tsx`); there is no sheet. Import state lives in a module-level `ImportManager` store read via `useSyncExternalStore` (ADR-018). See [frontend.md](frontend.md).

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

**Context:** The application stores irreplaceable user data (image metadata, tags, image groups, CLIP embeddings) across three stores: SQLite, the hash-sharded filesystem, and LanceDB. With no backup strategy, a disk failure or an accidental `reset_database.py` run means total data loss. Additionally, the original `init_db()` function used ad-hoc hand-rolled `ALTER TABLE` statements with no version tracking, making schema evolution fragile and difficult to reason about.

**Decision:** Two separate concerns addressed together:

1. **Automated backups**: A `backup_database` function in `backend/pipeline/maintenance.py` creates a consistent SQLite snapshot (using the `sqlite3.backup()` API, not file copy) and a LanceDB backup. It rotates old backups: keep last 7 daily + 4 weekly. Scheduled every 24h via the Scheduler. A companion `cleanup_staging` function removes stale import staging directories (>24h old) every 6h.

2. **Alembic for schema migrations**: The hand-rolled migration code in `init_db()` is replaced with Alembic. A single initial migration (`001_initial_schema.py`) captures the complete current schema including FTS5 virtual table and triggers. `init_db()` now detects whether the database is fresh (runs all migrations), pre-Alembic (stamps at head), or already Alembic-managed (runs pending migrations). Future schema changes are added as numbered Alembic migration files.

**Consequences:**
- Backups: daily snapshots with rotation; restore procedure documented in tests (`test_backup_restore.py` proves the backup is restorable)
- Staging cleanup: disk space no longer leaks from crashed or abandoned imports
- Alembic: schema changes are versioned, reviewable, and revertable; `alembic upgrade head` is the canonical way to apply migrations
- The `alembic.ini` at project root allows CLI use: `uv run alembic upgrade head`
- Image store files are not backed up by the script — they are large, append-only blobs and the originals typically exist elsewhere; document this assumption
- LanceDB embeddings can be regenerated from images via `write_new_embeddings` if the LanceDB backup is unavailable
- **Status note (2026-10):** `cleanup_staging` no longer exists; staging is cleaned by item state (ADR-018). Scheduled tasks are now `backup_database` (24h), `ingest_maintenance` (6h), `sweep_orphaned_store_files` (24h) and `reconcile_vectors` (24h); see [ingestion.md](ingestion.md#9-maintenance-and-recovery). There is no `reset_database.py`.

---

## ADR-011: Terminology rename and image_type field

**Date:** 2026-02
**Status:** Accepted

**Context:** The original codebase used "variant group" / "sub-variant" / "variants" terminology inherited from the early battlemap-only scope. As the tool broadened to handle non-battlemap images (character portraits, scene illustrations, tokens, etc.), the naming became confusing — "variant" conflated the concept of a group member with the broader "image variant" meaning. Additionally, the `BattlemapParser` name and `map_name` field were too domain-specific.

The system also needed a way to distinguish between battlemaps (which have grid metadata) and other image types like scenes (which do not).

**Decision:** Two changes made together:

1. **Terminology rename:**
   - "variant group" → "group" (or "image group"); `VariantGroup` model → `ImageGroup`
   - "sub-variant" → "subgroup"; `sub_variant` field → `subgroup`
   - "variants" (individual images in a group) → "scenes"
   - `BattlemapParser` → `ImageParser`; `battlemap_parser.py` → `image_parser.py`
   - `map_name` → `name`
   - `variant_group_name` → `group_name`
   - `/variant-groups` API route → `/groups`

   SQLAlchemy column aliases are used to map old DB column names to new Python attribute names, avoiding a database migration for the rename. For example, `Column("variant_group_name", ...).label("group_name")` or using the `key` parameter. This keeps the physical schema stable while the application code uses the new names.

2. **`image_type` field:**
   - New `image_type` column on `Image` (values: `"battlemap"`, `"scene"`; default: `"battlemap"`)
   - `ImageParser` is type-aware: scenes skip grid detection and use a reduced junk word list
   - Gallery gains a type filter in the filter panel
   - Import dialog gains a per-file type selector (override from default)
   - ImageViewer conditionally hides grid UI for scene-type images

**Consequences:**
- No database migration needed for the rename (column aliasing approach)
- All new code uses the new terminology; old DB column names are an implementation detail
- `image_type` enables type-specific behavior in both parser and UI
- Future image types (e.g., "token", "handout") can be added by extending the enum
- The column aliasing pattern means raw SQL queries against the DB still use old column names — documented for anyone inspecting the DB directly

---

## ADR-012: In-process job execution (replacing Prefect)

**Date:** 2026-02
**Status:** Accepted (supersedes ADR-003, ADR-007)

**Context:** Prefect required Docker infrastructure (Prefect server, Postgres, Redis) plus a local worker process. This was heavyweight for a single-user desktop tool: 5 containers running for what amounts to background task execution. Deployment registration, worker polling latency (~2-5s per job start), and cross-process result passing added unnecessary complexity. The observability benefits were rarely used in practice.

**Decision:** Replace Prefect with two in-process services:

1. **JobRunner** (`backend/app/services/job_runner.py`):
   - In-process `ThreadPoolExecutor` with bounded concurrency (default 2 workers)
   - Submits background functions (import processing, retagging, backfills, embedding rebuilds)
   - Tracks job status (`queued`, `running`, `completed`, `failed`), progress percentage, and result in memory
   - Supports `progress_fn` callback for real-time status updates
   - Status exposed via `/api/v1/jobs/` REST endpoints
   - `run_sync()` method for synchronous execution (used by `analyse_upload`)

2. **Scheduler** (`backend/app/services/scheduler.py`):
   - Lightweight asyncio-based periodic task runner
   - Registers maintenance functions with fixed intervals (backup every 24h, staging cleanup every 6h)
   - Runs inside the FastAPI application lifespan
   - Executes tasks via `loop.run_in_executor()` to avoid blocking the event loop

Pipeline functions in `backend/pipeline/` are now plain Python functions — no decorators, no serialization constraints. They can be called directly (CLI), submitted to JobRunner (API), or scheduled (Scheduler).

**Consequences:**
- Zero external infrastructure — no Docker, no Postgres, no Redis
- Sub-second job start latency (direct function call vs. worker polling)
- No cross-process serialization — functions share the FastAPI process's memory (CLIP model, DB engine, LanceDB connection)
- Job status is in-memory only; lost on server restart (acceptable for a desktop tool)
- Frontend Activity tray shows background job progress via polling `/api/v1/jobs/`
- CLI scripts still work directly: `uv run python -m backend.pipeline.<script>`
- The `flow_run_id` column was dropped from `ImportGroupJob` (migration 005)
- **Status note (2026-10):** The import model described here is superseded by ADR-018: imports run on a dedicated `IngestWorker`, not `JobRunner`, and `ImportGroupJob` is gone. `run_sync()` and `analyse_upload` were removed. `JobRunner` remains for maintenance jobs, backfills, model downloads and embedding rebuilds; the Scheduler's current tasks are listed under ADR-010.

---

## ADR-013: Electron for desktop deployment (over Tauri)

**Date:** 2026-02
**Status:** Accepted

**Context:** The project needs a desktop app for non-technical users. Two approaches were evaluated in detail (see archived plans `plan-electron-desktop.md` and `plan-tauri-desktop.md`):

- **Tauri v2** — Rust-based shell, smaller binary (~300-500MB), native webview. Requires Rust toolchain, more complex sidecar management, less mature ecosystem for Python sidecar bundling.
- **Electron** — Node.js-based shell, larger binary (~450-650MB due to bundled Chromium), mature ecosystem. TypeScript main process, straightforward sidecar management via `child_process`, well-established `electron-builder` for multi-platform packaging.

**Decision:** Use Electron. The main factors:

1. **No Rust requirement** — all desktop code is TypeScript, matching the frontend skill set
2. **Simpler sidecar bundling** — `extraResources` in electron-builder copies the PyInstaller output directly; no Rust-side process management needed
3. **Mature auto-updates** — `electron-updater` provides built-in GitHub Releases integration
4. **Proven ecosystem** — electron-builder handles code signing, DMG/NSIS/AppImage/DEB packaging across all platforms
5. **Binary size difference (~150MB) is acceptable** for a tool that bundles a full ML model (~600MB CLIP) regardless of shell choice

**Consequences:**
- Desktop app bundles Chromium (~150MB overhead vs native webview)
- Main process in TypeScript (`electron/src/main.ts`) handles windowing, IPC, sidecar lifecycle
- PyInstaller `--onedir` output bundled as `extraResources/sidecar/`
- Borderless window with platform-specific titlebar (hiddenInset on macOS, titleBarOverlay on Windows/Linux)
- See [electron.md](electron.md) for full architecture documentation

---

## ADR-014: Replace torch+transformers with ONNX Runtime for CLIP inference

**Date:** 2026-03
**Status:** Accepted

**Context:** The PyInstaller sidecar ships `libtorch_cpu.so` (~388 MB) and the full `transformers` package (~57 MB) — roughly 58% of the ~768 MB sidecar. The backend only uses CLIP for generating 512-d image and text embeddings. Running inference via `onnxruntime` with pre-exported ONNX graphs removes both heavy dependencies.

**Alternatives considered:**
- **FP32 ONNX** — Direct export, ~577 MB models. Larger than torch but removes torch dependency.
- **FP16 ONNX** — Half-precision quantisation, ~289 MB models. Negligible accuracy loss (max dot-product diff from torch: 0.0004).
- **INT8 ONNX** — Dynamic quantisation, ~146 MB models. Text encoder accuracy unacceptable (dot-product diff up to 0.36).

**Decision:** Ship FP16-quantised ONNX models bundled into the sidecar. Use `onnxruntime` (CPU) + `tokenizers` for inference. Keep `torch` and `transformers` as dev-only dependencies for the export script and comparison tests.

**Key changes:**
- `backend/app/services/clip_service.py` — Rewritten to use ONNX Runtime; same public interface (`CLIPService`, `get_clip_service()`)
- `scripts/models/export_model_onnx.py` — Exports optimised ONNX models + tokenizer from the torch model; quality evaluation via `--image-dir`
- `backend/pyinstaller/scene_atlas_backend.spec` — Removed torch/transformers, bundles optimised ONNX models
- Image preprocessing done with PIL + numpy (no `CLIPImageProcessor` dependency)
- Text tokenization via `tokenizers.Tokenizer` from exported `tokenizer.json`

**Quantisation test results (50 images, 13 text queries):**
| Variant | Vision Max Diff | Text Max Diff | Model Size |
|---------|----------------|---------------|------------|
| fp32    | 0.000001       | 0.000000      | 577.5 MB   |
| fp16    | 0.000384       | 0.000331      | 289.1 MB   |
| int8    | 0.039756       | 0.363677      | 145.6 MB   |

**Consequences:**
- **Update (2026-03):** The 'bundled models' consequence was superseded by ADR-017, which moved to HuggingFace-hosted model downloads.
- Sidecar drops from ~768 MB to ~350 MB (estimated, with fp16 models + onnxruntime)
- No first-run HuggingFace download (models are bundled)
- ONNX models must be re-exported when changing the base model (`scripts/models/export_model_onnx.py`)
- `backend/models/` is gitignored; CI must run the export script before building
- **Status note (2026-10):** small and medium are now fine-tuned 4-bit (w4a16) models released by scene-atlas-learning (`release_source` in `backend/app/services/model_registry.py`); large is fp16 throughout and is the only model `export_model_onnx.py` exports. The int8 export path was removed; [onnx-int8-quantisation.md](onnx-int8-quantisation.md) keeps the research. The runtime still runs an int8 text encoder on CPU if a manifest declares one.

---

## ADR-015: Dedicated backend endpoint for grouped search

**Date:** 2026-03
**Status:** Accepted

**Context:** The grouped view (Hero + Mosaic cards) originally used client-side grouping: fetch flat `Image[]` from `/search`, then group locally in `useImageGrouping`. This created two critical issues:

1. **Pagination conflict:** Image-level pagination (limit: 2000) doesn't align with group-level display. Groups could be split across pages, breaking layout and breaking Edit All when total matching images exceeded 2000.

2. **Edit All truncation:** The "Edit All" feature for mass-editing multiple groups needs all matching image IDs. With image-level pagination, it silently truncated results at 2000 images regardless of actual group size.

3. **Filter spreading bug:** The original Edit All handler spread `search.filters` (an `ActiveFilter[]` array) as an object, producing integer-keyed properties and silently losing filter context.

**Decision:** Implement dedicated `/api/v1/search/groups` endpoint returning pre-grouped results:

1. **Backend**:
   - New endpoint handles browse mode (all groups, sorted alphabetically) and search mode (groups sorted by best-score, only matching image IDs).
   - Accepts `include_all_image_ids=true` to populate `all_image_ids` field with in-scope image IDs for Edit All seeding.
   - Browse mode: batch query groups with all image IDs. Search mode: leverage pre-computed RRF scoring.
   - Paginated at group level: default 25/page, max 500 groups to prevent query explosion.

2. **Frontend**:
   - New `SeedImage` type (`{ id: number; group_id: number | null }`) for Edit All seeding — only requires `id` and `group_id`.
   - `Edit All` button fetches groups with `include_all_image_ids: true`, maps response to `SeedImage[]`.
   - Uses `search.groupSearchParams` (proper `SearchParams` object) instead of broken filter spread.
   - Threshold raised to 500 groups (matches backend capacity).

3. **Type safety**:
   - `Image[]` is structurally assignable to `SeedImage[]` (backward compatible for individual view).
   - `useEditGroupLoad` marks non-seeded images as `outOfScope` in dialog (applies identically to browse, search, and individual views).

**Consequences:**
- Edit All now works reliably up to 500 groups, with no image count cap
- Active filters properly passed to grouped view (filter spreading bug fixed)
- Groups are never split across pages (pagination at group level)
- Backward compatible: `Image[]` assignable to `SeedImage[]`; `all_image_ids` field is optional
- Backend query efficiency: single batch query (browse) or zero extra queries (search mode reuses RRF scoring)
- Relevance slider filtering is client-side (instant raise) or debounced refetch (lower); pagination resets to page 0
- **Status note (2026-10):** The default page size is 50 groups (`GET /search/groups` `limit` default; `PAGE_SIZE` in `useGroupSearch`), max 500. Browse mode sorts by `created_at desc` by default. Grouping logic lives in `backend/app/services/search_service.py`.

---

## ADR-016: Multi-model embedding support via manifest files

**Date:** 2026-03
**Status:** Accepted

**Context:** We want to support multiple embedding models (OpenCLIP, SigLIP2) with different preprocessing requirements, tokenizers, and embedding dimensions. We need easy model switching for dev/testing and model-scoped LanceDB tables.

**Decision:**
- Ship a `manifest.json` alongside each model's ONNX files capturing all model-specific parameters (image size, normalization, interpolation, resize mode, tokenizer config, embedding dimension, EOS token ID)
- CLIPService reads manifest at init and configures itself — no strategy pattern or plugin registry
- Model-scoped LanceDB tables: `embeddings_{model_name}`, enabling instant switching without re-embedding
- `vector_size` is auto-derived from the manifest's `embedding_dim` at startup, before any LanceDB service is created — model identity flows through table names, not dimension matching
- sentencepiece added as production dependency (~1MB) for SigLIP2's tokenizer, with a thin wrapper that replicates HF tokenizer behaviour (including EOS token appending)
- Own export script (`export_model_onnx.py`) for full control over quantisation and manifest generation
- Manifest validation at load time catches missing/malformed fields early
- Backward-compatible fallback: if no manifest exists, hardcoded CLIP ViT-B/32 defaults are used

**Alternatives considered:**
- Strategy pattern: over-engineered for models that all follow the same ONNX inference path
- JAX for ONNX export: requires jax2tf→tf2onnx (fragile, two conversion steps)
- Pre-exported ONNX from onnx-community: less control over quantisation choices
- tokenizer.json conversion for SigLIP2: fragile, may lose text lowercasing and EOS token behaviour
- Dimension-based model compatibility checking: weak proxy — two models can share dimensions but produce incompatible embeddings; model identity is better encoded in table names

**Consequences:**
- Adding a new model requires only: export script run + manifest generation
- Model switch in dev: set `EMBEDDING_MODEL` env var, restart server; auto-rebuild triggers if table is missing or has wrong count
- All dev/build scripts (`setup_models.py`, `build_sidecar.py`, `export_model_onnx.py`, PyInstaller spec) respect `EMBEDDING_MODEL` env var
- sentencepiece adds ~1MB to production dependency footprint
- Models directory structure: `backend/models/{model-name}/` (flat: ONNX files + manifest.json + tokenizer/)

---

## ADR-017: HuggingFace-hosted model distribution

**Date:** 2026-03-15
**Status:** Accepted

**Context:** ONNX models were previously bundled in `backend/models/` (gitignored, produced by `export_model_onnx.py`). This required developers to run the export script before the backend would start, and made it impossible for non-technical users to choose a model or download an updated version. The three models (`small`/`medium`/`large`) are now published to HuggingFace under the `jennis0` namespace as pre-built ONNX packages.

**Decision:** Ship models on HuggingFace; download on first boot or on explicit user selection.

Key choices:

1. **Download location:** `APP_DATA_DIR/models/{name}/` — user-owned, on fast storage, consistent with the split-storage spec. Dev fallback to `backend/models/{name}/` (still used by developers and CI).

2. **Completion marker:** `version.json` written *last*, after all files are verified. `is_model_downloaded()` checks only for `version.json` — any directory without it is treated as incomplete.

3. **Atomic download:** Downloads go to a temp dir (`.tmp/{name}/`), files are verified, then the temp dir is renamed to the final location in a single filesystem operation. A crash mid-download leaves no unusable partial state.

4. **Active model source:** `EMBEDDING_MODEL` env var → DB `app_settings.active_model` → auto-detect (GPU present → `medium`, CPU-only → `small`). The `active_model` DB key is intentionally not seeded on first boot so auto-detect runs on fresh installs.

5. **`active_model` not in `AppSettingsPatch`:** Switching the active model triggers a multi-step background job (download, service reload, re-embed). Routing it through the generic settings PATCH would obscure that intent and risk skipping the job. A dedicated `POST /api/v1/models/active` endpoint makes the side-effects explicit.

6. **Model switch sequence:** `POST /active` submits `_download_and_activate` to JobRunner which sequences: download → `reload_clip_service()` → `wait_for_clip_ready()` → `reload_lancedb_service(f"embeddings_{name}")` → `rebuild_all_embeddings(force=True)`. `force=True` is required because the existing embeddings are for the old model and the skip-if-present guard must not fire.

7. **Model registry as single source of truth:** `backend/app/services/model_registry.py` contains all model specs (HF repos, descriptions, hardware recommendations, quantisation parameters). Export and publish scripts import from this module rather than maintaining their own inline registry.

8. **No auto-update:** `version.json` stores `hf_commit_sha` to enable future update detection, but no polling or auto-download is implemented. Intentional — compute overhead and user expectation around background downloads.

**Consequences:**
- Non-technical users can choose a model via the UI (or accept the hardware-aware default)
- CI uses `huggingface_hub.snapshot_download` to fetch pre-built ONNX — no torch/transformers needed in CI
- A fresh install with no model in `APP_DATA_DIR` starts the backend in a degraded state (CLIPService fails to load); web mode shows a blocking `ModelSetupScreen` overlay
- Stale embeddings from previous models are preserved in named LanceDB tables (`embeddings_{name}`) — user can delete via `DELETE /api/v1/models/{name}/embeddings`
- The large model is never auto-recommended; it requires explicit selection

---

## ADR-018: Durable per-item ingest pipeline

**Date:** 2026-10-15
**Status:** Implemented (PR #1; stored format added in the Phase 6 PR). Supersedes the import model in ADR-012 and the earlier import job state machine. Not yet done: perceptual "possible duplicate" flags (point 6). Current behaviour: [ingestion.md](ingestion.md).

**Context:** A reliability audit (2026-10-12) found about 50 issues in the import flow. Three structural causes account for nearly all of them.
1. **An import job was an all-or-nothing transaction.** A restart, a failed group, or dismissing a failed job deleted every image the job had imported. This existed to avoid false duplicate matches.
2. **There was no durable per-file state.** The work list lived in `JobRunner` kwargs in memory, so nothing could resume, cancel couldn't stop the worker, and maintenance timers could delete long imports part-way through.
3. **The browser drove the lifecycle.** Upload, analyse and auto-confirm ran in React effects, so tab closes, remounts and races stranded jobs in non-terminal states.

Duplicate detection was also broken under WebP conversion, and imports over ~32k files hit SQLite's variable limit.

**Decision:** Replace the import pipeline with a durable, per-item model. Full design: [ingestion.md](ingestion.md).

1. **A job contains groups, and a group contains items.** Jobs remain the user-facing unit. Every file is an `import_items` row holding its own state (`awaiting_bytes`, `ready`, `processing`, `done`, `duplicate`, `failed`, `skipped`), attempts, classified error and resulting image. Job progress is derived from item counts.
2. **Jobs have four states (`active`, `paused`, `completed`, `cancelled`) and never fail as a whole.** Cancel keeps finished work. Deleting imported images happens only through an explicit "Undo import". Dismiss only hides.
3. **A dedicated `IngestWorker`, separate from `JobRunner`,** claims items in batches, round-robin across jobs. Each batch commits in one `BEGIN IMMEDIATE` transaction with temp-then-rename file placement. LanceDB is written after commit and repaired by id-set reconciliation. Startup recovery returns in-flight items to `ready`, and an item that crashes processing 3 times is failed.
4. **Errors are classified as `file`, `transient` or `system`.** File errors fail the item. Transient errors are retried with backoff. System errors (disk full, model missing or switching, library unavailable) pause the queue with a reason instead of failing anything.
5. **Uploads send the file list first, then the bytes:** a chunked manifest, then seal (parse and group server-side), then one idempotent raw `PUT` per file. Processing overlaps the upload. Interrupted uploads can be resumed by re-picking the files.
6. **Duplicate detection has three tiers.**
   - Exact original-bytes SHA-256: auto-skip, and checked client-side before upload.
   - Canonical decoded-pixel hash: auto-skip at commit.
   - Perceptual hash: advisory "possible duplicate" only, never auto-skipped, because battlemap variants are near-duplicates by nature.

   "Import as new copy" processes the file as fully independent (own stored file, thumbnails and embedding). It is the escape hatch for a faulty match, so it shares nothing with the matched image. The shared-storage reuse path is removed.
7. **The frontend has one `ImportManager` store** outside React. It owns uploads, a hashing Web Worker and a single ETag-aware poller; dialogs and the dock are pure views.
8. **Stored-file conversion defaults to off.** The `stored_format` setting (`original`/`webp`/`jpeg`/`png`, plus quality and lossless-for-lossless-sources) converts new imports on a worker temp copy; source and pixel hashes always come from the upload.

**Alternatives considered:**
- **Patch the existing flow finding by finding.** Rejected: the stuck and destructive states are emergent from the all-or-nothing job model and client-driven lifecycle.
- **Keep running imports through `JobRunner`.** Rejected: imports would queue behind model downloads and rebuilds, and there would be no natural place for claim, recovery and system-pause logic.
- **Perceptual-hash auto-skip with a strict threshold.** Rejected: gridded/gridless and prop variants fall inside any useful threshold.
- **Hashing after conversion.** Rejected: it depends on settings and encoder, lossy output loses its link to the source, and it can't be computed client-side.
- **Leases on claimed items.** Not needed under the single-process backend; revisit if multiple backend processes are introduced.

**Consequences:**
- Restarts, crashes and network loss no longer lose or delete work.
- Every import reaches a terminal state, or a clearly displayed waiting state.
- Removed: `import_group_jobs`, `analysis_result`/`file_errors` JSON, `.file_map.json`, `confirm-all`, `/fail`, `mark_interrupted_jobs`, `expire_stale_jobs`, the per-job FTS rebuild, and six frontend import hooks.
- More HTTP requests per import (one per file). Reverse-proxy rate limits must allow for this.
- The future bulk local-library import becomes another source of bytes for the same item queue.
- Scene Atlas is unreleased, so no data migration is provided.

---

## ADR-019: Grid detector v3 (spectral comb plus trained classifiers)

**Date:** 2026-10-16
**Status:** Implemented (PR #2)

**Context:** The original detector (Canny edges plus autocorrelation, 8000 px cap) peaked at about 1.6 GB per map. It called grids on 28% of explicitly gridless maps, and made spurious hex calls. Five evaluation rounds against labels from gridded/gridless "twins" across 28 creators (see [grid-detection-v3.md](grid-detection-v3.md)) showed that a harmonic-comb detector with small trained classifiers is better. Measured by leaving one creator out at a time, v3's worst-creator F1 is .685 against .667 for the current detector, and its median is .944 against .913. It also gets the grid size exactly right more often: .945 vs .875.

**Decision:**
1. **Detector.** v3 handles maps whose longest side is 1000 px or more. It analyses at full resolution, with a harmonic comb over line-energy profiles, a per-image null distribution, spatial-coverage features and two hex measures. The decisions come from a gradient-boosted presence model and a hex logistic regression, shipped as ONNX in `backend/app/data/grid_models` and run on the CPU through the onnxruntime the app already includes.
2. **Small maps.** Maps under 1000 px keep the legacy detector, where v3 measured worse.
3. **One analysis setting.** The old tuning settings are removed. `grid_analysis_max_dim` (0 = full resolution) remains, and lowering it costs accuracy on thin-line, high-dpi maps.
4. **Grid source.** Each image records where its grid came from: `images.grid_source` is `filename`, `detector` or `user`. Re-detection never overwrites `user`, nor explicit file-name labels ("No Grid", or an exact NxM).
5. **Sibling sizes.** In size-only mode, NxM sizes from other file names in the same group are scored as candidate tile counts. They are never taken as truth.
6. **Reproducible models.** `scripts/models/grid/train_grid_models.py` rebuilds the models byte-for-byte from a features file. Images and features stay out of git because the maps are commercial artwork.

**Alternatives considered:**
- **v3 for every image size.** Rejected: it was worse on small maps in the cross-artist evaluation.
- **Hand-tuned thresholds without trained models.** Rejected: thresholds tuned on one dev sample did not hold on held-out creators (round 1).
- **Pickle or JSON models.** Rejected: pickle is unsafe and tied to the scikit-learn version, and the chosen presence model is a tree ensemble, which JSON doesn't suit.
- **Reduced-resolution analysis by default.** Rejected: 2-4x reduction blurred the 1-2 px lines on 200 dpi maps.

**Consequences:**
- Fewer false grids on gridless maps.
- More CPU on very large maps (up to about 28 s for a 761 Mpx map), with memory reserved through the ingest budget's per-format formula.
- Known limits: very dark thin-line maps, maps with only a few cells, perfectly regular one-directional patterns such as planks, and faint hex.
- The legacy detector remains only for small images.
