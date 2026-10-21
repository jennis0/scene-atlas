# Running Tests

For testing strategy, conventions, and guidelines on what to test, see [design/testing.md](https://github.com/jennis0/scene-atlas/blob/main/design/testing.md).

For stress testing the import pipeline, see [stress-testing.md](stress-testing.md).

## Pre-commit Setup

Run `npm install` at the repository root to activate Husky pre-commit hooks. This installs git hooks that run `lint-staged` (ruff + ESLint + Prettier) on staged files before committing. If you only run `uv sync` (Python setup), the pre-commit hooks will not be installed.

## Quick Reference

```bash
# All fast tests (unit + integration, ~20s)
uv run pytest backend/tests/unit backend/tests/integration -v

# Just parser tests (fastest feedback loop, ~5s)
uv run pytest backend/tests/unit/test_parser.py -v

# Frontend tests
cd frontend && npx vitest run

# Frontend tests with watch mode
cd frontend && npx vitest

# Electron and upgrade-test unit tests (node --test)
npm run test:electron

# Heavy tests (real CLIP ONNX model -- ~289MB FP16, setup via scripts/models/setup_models.py)
uv run python -m pytest -m heavy -v

# Run everything including heavy
uv run python -m pytest -m '' -v

# E2E tests (requires backend + frontend running, or let Playwright start them)
make test-e2e                    # headless Chromium
make test-e2e-ui                 # interactive UI mode for debugging
npm run test:e2e:headed          # headed Chromium (see the browser)
```

## Makefile Targets

```bash
make check          # lint + format-check (both backend + frontend)
make test           # unit tests + frontend tests (fast, ~15s)
make test-all       # unit + integration + frontend (downloads small model on first run)
make test-heavy     # CLIP model tests (downloads small model on first run)
make test-e2e       # Playwright E2E tests (Chromium, ~35s with warm servers)
make test-e2e-ui    # Playwright interactive UI mode (for debugging)
make test-cov       # full suite with coverage reporting
make lint-fix       # auto-fix all lint + format issues
```

## Integration Tests (CLIP model required)

Integration tests and heavy tests need a real ONNX model. `make test-integration` and `make test-heavy` automatically download the `small` model (~262 MB, quantized) on first run via `make ensure-model`. The model is cached locally and only downloaded once.

```bash
make ensure-model       # download small model if not present
make test-integration   # integration tests with EMBEDDING_MODEL=small
make test-heavy         # heavy tests with real CLIP inference
```

## Heavy Tests (CLIP)

Tests marked with `@pytest.mark.heavy` load the real CLIP ONNX model and run real inference. They are **excluded by default** via `addopts = "-m 'not heavy'"` in pyproject.toml. Currently only `test_clip_heavy.py` uses this marker.

**Model caching:**
- CI caches the small ONNX model with `actions/cache`, keyed on `backend/app/services/model_registry.py`
- The model is downloaded again only when that file changes

**Test fixture:** The `clip_service` fixture is `session`-scoped and also primes the module-level singleton, so both direct `CLIPService` usage and `get_clip_service()` code paths work.

## E2E Tests (Playwright)

Playwright tests validate critical user flows in a real browser against the full stack (real backend, real frontend, real CLIP model).

**Architecture:**
- Located in `e2e/` at project root (not inside `frontend/`) -- tests exercise the full stack
- Dual webServer config: Playwright starts both backend and frontend automatically
- Real CLIP model (no mocking) -- loads in a background thread, server responds immediately
- Test data seeded via the import API using real encrypted fixture images (decrypted at runtime from Git LFS). Without `E2E_IMAGE_KEY`, set `E2E_IMAGE_DIR` to a local folder of your own (non-commercial) images to seed from instead
- The backend runs against an isolated `e2e/.tmp-data` (`APP_DATA_DIR`; library in `.tmp-data/library`). The project's `data/models` is linked in so the model isn't downloaded twice. The suite starts its own backend on port 18000 and Vite on 15173 (`E2E_BACKEND_PORT`, `E2E_FRONTEND_PORT`), with Vite's `/api` proxy pointed at that backend through `API_PROXY_TARGET`, so it never reuses a development backend on :8000 or writes test data into its library. Locally, servers already listening on those ports are reused
- Serial execution (`workers: 1`) -- tests share backend state
- Chromium only in CI; Firefox/WebKit available locally via `--project` flag

**Key files:**
- `e2e/playwright.config.ts` -- Dual webServer, serial execution, CI/local reporter config
- `e2e/fixtures/base.ts` -- Worker-scoped auto fixture that decrypts real images and seeds via API
- `e2e/helpers/seed.ts` -- Import API (ADR-018): create job → manifest (first 2 files as scenes, the rest battlemaps) → seal → hashes → PUT bytes per item → poll `GET /imports/{id}` until finished; throws listing any failed items
- `e2e/helpers/images.ts` -- Generates unique random PNGs, so import tests always add something new
- `e2e/helpers/decrypt-fixtures.ts` -- Decrypts `e2e-images.zip.enc` (Git LFS) for CI and local dev

**`reuseExistingServer`:** Locally, if you already have the backend and frontend running, Playwright reuses them -- no cold-start overhead. In CI, Playwright starts both servers fresh.

**Test coverage (12 spec files):**
- `smoke.spec.ts` -- Health check, page load, seeded data visible
- `gallery.spec.ts` -- Image count, type tabs, view toggle, sort dropdown
- `gallery-deep.spec.ts` -- Text-only search, semantic search, filters, clear all, empty state, grouped view
- `search.spec.ts` -- Text search, clear, semantic prefix with relevance slider
- `image-viewer.spec.ts` -- Open/close modal, keyboard navigation, delete navigation
- `import.spec.ts` -- Import dialog start view: pickers, battlemap/scene toggle, Escape closes
- `upload-flow.spec.ts` -- Search, semantic search, author filter, metadata viewer on seeded data
- `import-deep.spec.ts` -- New file: progress view → finished → report counts → confirmed undo restores the gallery count; re-importing a library file is reported under "Already in library"
- `edit-group.spec.ts` -- Context menu open, group images/metadata, escape close
- `activity-dock.spec.ts` -- Closing the dialog keeps the import in the dock; its row shows the outcome and opens the report
- `accessibility.spec.ts` -- axe WCAG 2.2 AA scans of the main surfaces in every palette, theme and contrast level; keyboard path through the core task
- `zoom.spec.ts` -- At the equivalent of 200% zoom with larger text, the main controls stay reachable

## Test File Structure

```
backend/tests/
├── conftest.py                    # Shared fixtures, LanceDB/CLIP mocking
├── test_prepare_pool.py           # Global prepare pool
├── test_seed_settings.py          # seed_default_settings
├── unit/                          # Pure logic, no DB, no filesystem side effects
│   ├── test_parser.py             # ImageParser.parse() and group_files()
│   ├── test_schemas.py            # Pydantic model validation and round-trips
│   ├── test_naming.py             # export_path, download_filename, sanitize_segment
│   ├── test_pipeline_tasks.py     # color_extraction, image_processing, grid_detection, embedding
│   ├── test_pipeline_db.py        # pipeline_db() session helper
│   ├── test_video_utils.py        # verify_video_mime, extract_first_frame, get_video_dimensions
│   ├── test_color_search.py       # hex to LAB, SQL delta E colour search
│   ├── test_deletion_service.py   # safe_delete_image, delete_image_rows
│   ├── test_system_info.py        # dir_size utility
│   ├── test_path_traversal.py     # Path traversal prevention
│   ├── test_validation.py         # Upload validation helpers
│   ├── test_ingest_state.py       # Import item/job state machine transitions
│   ├── test_error_classifier.py   # Ingest error kinds (file / transient / system)
│   ├── test_image_hashes.py       # SHA-256, pixel hash, pHash
│   ├── test_memory_budget.py      # Memory-aware prepare admission
│   ├── test_stored_format.py      # Stored-format conversion rules
│   ├── test_settings_seed.py      # CONVERT_TO_WEBP → stored_format seeding
│   ├── test_fts_service.py        # FTS5 full-text search
│   ├── test_grid_detector.py      # GridDetector service
│   ├── test_grid_v3.py            # Grid detection v3 on synthetic images
│   ├── test_grid_pipeline_rules.py # Grid memory estimates, backfill selection
│   ├── test_grid_regression_local.py # Opt-in regression on a local map library
│   ├── test_image_store.py        # Hash-sharded filesystem storage
│   ├── test_maintenance.py        # Backups + orphan sweep
│   ├── test_scheduler.py          # Periodic task scheduler
│   ├── test_lancedb_service.py    # LanceDBService against a real tmp LanceDB
│   ├── test_clip_service.py       # CLIPService module helpers
│   ├── test_config_mode.py        # APP_MODE config detection
│   ├── test_config_roots.py       # APP_DATA_DIR + IMAGE_LIBRARY_DIR split
│   ├── test_database_pragmas.py   # SQLite pragmas
│   ├── test_logging_config.py     # Logging configuration
│   ├── test_security_headers.py   # SecurityHeadersMiddleware
│   ├── test_ort_providers.py      # ONNX Runtime execution provider selection + fallback
│   ├── test_manifest.py           # Model manifest loading and validation
│   ├── test_model_registry.py     # Model registry helpers
│   ├── test_model_download_service.py # Model downloads
│   ├── test_tag_packs.py          # Tag pack import service
│   ├── test_vocabulary.py         # Tag vocabulary loader
│   └── test_resource_detector.py  # compute_resource_defaults concurrency scaling
├── integration/                   # Real SQLite DB, mocked CLIP/LanceDB
│   ├── test_ingest_pipeline.py    # IngestWorker driven by drain(): commit, dedup, recovery, system pause, reconciliation
│   ├── test_imports_api.py        # /imports API: manifest, seal, hashes, content PUT, archives, control, undo
│   ├── test_search_endpoint.py    # GET /api/v1/search/ + facets
│   ├── test_images_endpoint.py    # GET/PATCH/DELETE /api/v1/images/ + scenes + file serving
│   ├── test_groups_endpoint.py    # Groups CRUD, merge, move-images, download
│   ├── test_tags_endpoint.py      # Tags/categories CRUD + cascading
│   ├── test_export_endpoint.py    # GET /api/v1/export/library (ZIP structure + metadata)
│   ├── test_models_api.py         # /api/v1/models/ endpoints
│   ├── test_rate_limits.py        # Rate limiting
│   ├── test_system_admin.py       # Library purge, tag reset
│   ├── test_system_endpoint.py    # GET /api/v1/system/info
│   ├── test_health_endpoint.py    # GET /health deep health check
│   ├── test_backup_restore.py     # Backup + restore pipeline
│   ├── test_migration_022.py      # Migration 022 (grid source labelling)
│   ├── test_migration_024.py      # Migration 024 (colour LAB backfill, threshold units)
│   └── test_clip_heavy.py         # Real CLIP model tests (marked @heavy, excluded by default)

e2e/                                  # Playwright E2E tests (full stack, real browser)
├── playwright.config.ts              # Dual webServer (backend + frontend)
├── tsconfig.json
├── fixtures/
│   ├── base.ts                       # Worker-scoped seed fixture (decrypts + seeds via API)
│   └── e2e-images.zip.enc           # Encrypted real test images (Git LFS)
├── helpers/
│   ├── actions.ts                    # Reusable test helpers (gallery, import, search, filter)
│   ├── config.ts                     # Backend URL config
│   ├── decrypt-fixtures.ts           # Decrypt encrypted fixture archive
│   ├── images.ts                     # Unique synthetic PNGs for import tests
│   └── seed.ts                       # API-based data seeding orchestration
└── tests/
    ├── smoke.spec.ts                 # Health check, page load, seeded data
    ├── gallery.spec.ts               # Image display, type tabs, view toggle, sort
    ├── gallery-deep.spec.ts          # Text-only search, semantic, filters, grouped view
    ├── search.spec.ts                # Text search, semantic prefix, clear
    ├── image-viewer.spec.ts          # Modal open/close, keyboard nav, delete nav
    ├── import.spec.ts                # Import dialog start view
    ├── upload-flow.spec.ts           # Search, filter, metadata viewer
    ├── import-deep.spec.ts           # Import → report → undo; duplicate skipped
    ├── edit-group.spec.ts            # Context menu, group metadata, escape close
    ├── activity-dock.spec.ts         # Dock row → report
    ├── accessibility.spec.ts         # axe WCAG scans, keyboard path
    └── zoom.spec.ts                  # 200% zoom + larger text

frontend/src/
├── components/
│   ├── ActivityDock.test.tsx
│   ├── DesktopGate.test.tsx
│   ├── EditGroupDialog.test.tsx
│   ├── LibraryInfoDialog.test.tsx
│   ├── import/
│   │   ├── fileFilter.test.ts
│   │   ├── tagColors.test.ts
│   │   └── types.test.ts
│   └── imports/
│       └── imports.test.tsx         # Dialog, dock row and report over a real ImportManager + fake client (test/importFakes.ts)
├── contexts/
│   └── ThemeContext.test.tsx
├── hooks/
│   ├── useEditGroupOperations.test.ts
│   ├── useFileEditing.test.ts
│   ├── useGalleryDialogs.test.ts
│   ├── useGallerySearch.test.ts
│   ├── useImageGrouping.test.ts
│   ├── useJobPolling.test.ts
│   └── useSettingsDraft.test.tsx
└── lib/
    ├── apiBase.test.ts
    ├── appMode.test.ts
    ├── categoryIcons.test.ts
    ├── constants.test.ts
    ├── getErrorMessage.test.ts
    └── import/
        └── ImportManager.test.ts    # Uploads, retry, resume, poller/ETag, hash fallback
```
