# Running Tests

For testing strategy, conventions, and guidelines on what to test, see [design/testing.md](../design/testing.md).

For stress testing the import pipeline, see [stress-testing.md](stress-testing.md).

## Pre-commit Setup

Run `npm install` at the repository root to activate Husky pre-commit hooks. This installs git hooks that run `lint-staged` (ruff + ESLint + Prettier) on staged files before committing. If you only run `uv sync` (Python setup), the pre-commit hooks will not be installed.

## Quick Reference

```bash
# All fast tests (unit + integration, ~20s)
uv run pytest backend/tests/unit backend/tests/integration -v

# Just parser tests (fastest feedback loop, ~5s)
uv run pytest backend/tests/unit/test_parser.py -v

# Just the critical round-trip test
uv run pytest backend/tests/integration/test_metadata_roundtrip.py -v

# Frontend tests
cd frontend && npx vitest run

# Frontend tests with watch mode
cd frontend && npx vitest

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
- ONNX models are cached in CI via `actions/cache@v4` keyed on `backend/app/services/model_registry.py`
- Models are only re-exported when the export script or config changes

**Test fixture:** The `clip_service` fixture is `session`-scoped and also primes the module-level singleton, so both direct `CLIPService` usage and `get_clip_service()` code paths work.

## ONNX Model Assessment

Quality evaluation is integrated into `scripts/models/export_model_onnx.py` via the `--image-dir` flag. When provided, the export script runs a comprehensive quality assessment using the torch model (still loaded from the export phase) as reference.

**When it runs:**
- Locally: `make evaluate-onnx` or `uv run python scripts/models/export_model_onnx.py clip-vit-b-32 --image-dir /path/to/images`
- Not in CI (requires real images and torch model; CI only does quick export)

**What it checks:**
- Cosine diffs (max, mean) for vision and text encoders vs torch reference
- Top-5 set preservation and Spearman rank correlation on real images
- Batch encoding consistency
- Aspect ratio stress tests
- Cross-modal ranking preservation
- Inference timing and model sizes
- Results written to `quantisation_quality` section of manifest.json

**Thresholds:** fp32=0.001, fp16=0.001, int8=0.01

## E2E Tests (Playwright)

Playwright tests validate critical user flows in a real browser against the full stack (real backend, real frontend, real CLIP model).

**Architecture:**
- Located in `e2e/` at project root (not inside `frontend/`) -- tests exercise the full stack
- Dual webServer config: Playwright starts both backend and frontend automatically
- Real CLIP model (no mocking) -- loads in a background thread, server responds immediately
- Test data seeded via the import API using real encrypted fixture images (decrypted at runtime from Git LFS)
- Serial execution (`workers: 1`) -- tests share backend state
- Chromium only in CI; Firefox/WebKit available locally via `--project` flag

**Key files:**
- `e2e/playwright.config.ts` -- Dual webServer, serial execution, CI/local reporter config
- `e2e/fixtures/base.ts` -- Worker-scoped auto fixture that decrypts real images and seeds via API
- `e2e/helpers/seed.ts` -- Uploads images via import API, confirms all groups, polls until done
- `e2e/helpers/decrypt-fixtures.ts` -- Decrypts `e2e-images.zip.enc` (Git LFS) for CI and local dev

**`reuseExistingServer`:** Locally, if you already have the backend and frontend running, Playwright reuses them -- no cold-start overhead. In CI, Playwright starts both servers fresh.

**Test coverage (37 tests across 10 files):**
- `smoke.spec.ts` -- Health check, page load, seeded data visible
- `gallery.spec.ts` -- Image count, type tabs, view toggle, sort dropdown
- `gallery-deep.spec.ts` -- Text-only search, semantic search, filters, clear all, empty state, grouped view
- `search.spec.ts` -- Text search, clear, semantic prefix with relevance slider
- `image-viewer.spec.ts` -- Open/close modal, keyboard navigation, delete navigation
- `import.spec.ts` -- Dialog open, file upload via file chooser
- `upload-flow.spec.ts` -- Upload, search, semantic search, author filter, metadata viewer
- `import-deep.spec.ts` -- Upload controls, type toggle, file upload processing
- `edit-group.spec.ts` -- Context menu open, group images/metadata, escape close
- `activity-dock.spec.ts` -- Dock pill after import, expanding dock shows job cards

## Test File Structure

```
backend/tests/
├── conftest.py                    # Shared fixtures, Qdrant/CLIP mocking
├── unit/                          # Pure logic, no DB, no filesystem side effects
│   ├── test_parser.py             # ImageParser.parse() and group_files()
│   ├── test_schemas.py            # Pydantic model validation and round-trips
│   ├── test_thumbnail_names.py    # Preview thumbnail filename consistency
│   ├── test_naming.py             # export_path, download_filename, sanitize_segment
│   ├── test_pipeline_tasks.py     # color_extraction, image_processing, grid_detection, embedding
│   ├── test_video_utils.py        # verify_video_mime, extract_first_frame, get_video_dimensions
│   ├── test_color_search.py       # HSL color distance, color index search
│   ├── test_deletion_service.py   # safe_delete_image, file + DB + Qdrant cleanup
│   ├── test_system_info.py        # dir_size utility
│   ├── test_path_traversal.py     # Path traversal prevention
│   ├── test_validation.py         # Input validation helpers
│   ├── test_import_state.py       # Import state machine transitions
│   ├── test_fts_service.py        # FTS5 full-text search
│   ├── test_grid_detector.py      # Image-based grid detection algorithm
│   ├── test_image_store.py        # Hash-sharded filesystem storage
│   ├── test_maintenance.py        # Backup + cleanup tasks
│   ├── test_config_mode.py        # APP_MODE config detection
│   ├── test_ort_providers.py      # ONNX Runtime execution provider selection + fallback
│   ├── test_manifest.py           # Model manifest loading and validation
│   └── test_resource_detector.py  # compute_resource_defaults concurrency scaling
├── integration/                   # Real SQLite DB, mocked CLIP/Qdrant
│   ├── test_metadata_roundtrip.py # User edits survive to DB (highest priority)
│   ├── test_analyse_upload.py     # analyse_upload (grouping + thumbnails)
│   ├── test_process_single.py     # process_single_image (both modes)
│   ├── test_process_import_group.py # process_import_group + process_import_job
│   ├── test_upload_endpoint.py    # POST /imports/upload
│   ├── test_confirm_endpoint.py   # POST /imports/{id}/confirm
│   ├── test_preview_endpoint.py   # GET /imports/{id}/preview/{path}
│   ├── test_imports_status.py     # GET /imports/{id}/status + active
│   ├── test_search_endpoint.py    # GET /api/v1/search/ + facets
│   ├── test_images_endpoint.py    # GET/PATCH/DELETE /api/v1/images/ + scenes + file serving
│   ├── test_groups_endpoint.py    # Groups CRUD, merge, move-images, download
│   ├── test_tags_endpoint.py      # Tags/categories CRUD + cascading
│   ├── test_export_endpoint.py    # GET /api/v1/export/library (ZIP structure + metadata)
│   ├── test_system_admin.py       # GET /api/v1/system/ endpoints
│   ├── test_system_endpoint.py    # System info + delete library
│   ├── test_health_endpoint.py    # GET /health deep health check
│   ├── test_backup_restore.py     # Backup + restore pipeline
│   ├── test_expire_stale_jobs.py  # Stale job expiry + staging cleanup
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
│   └── seed.ts                       # API-based data seeding orchestration
└── tests/
    ├── smoke.spec.ts                 # Health check, page load, seeded data
    ├── gallery.spec.ts               # Image display, type tabs, view toggle, sort
    ├── gallery-deep.spec.ts          # Text-only search, semantic, filters, grouped view
    ├── search.spec.ts                # Text search, semantic prefix, clear
    ├── image-viewer.spec.ts          # Modal open/close, keyboard nav, delete nav
    ├── import.spec.ts                # Upload dialog, file upload preview
    ├── upload-flow.spec.ts           # Upload, search, filter, metadata viewer
    ├── import-deep.spec.ts           # Upload controls, type toggle, processing
    ├── edit-group.spec.ts            # Context menu, group metadata, escape close
    └── activity-dock.spec.ts         # Dock pill, expanding job cards

frontend/src/
├── components/
│   ├── ActivityDock.test.tsx
│   ├── DesktopGate.test.tsx
│   ├── EditGroupDialog.test.tsx
│   ├── LibraryInfoDialog.test.tsx
│   └── import/
│       ├── fileFilter.test.ts
│       ├── tagColors.test.ts
│       └── types.test.ts
├── contexts/
│   └── ThemeContext.test.tsx
├── hooks/
│   ├── useEditGroupOperations.test.ts
│   ├── useFileEditing.test.ts
│   ├── useGalleryDialogs.test.ts
│   ├── useGallerySearch.test.ts
│   ├── useImageGrouping.test.ts
│   ├── useImportState.moveFiles.test.ts
│   ├── useImportUpload.test.ts
│   ├── useJobPolling.test.ts
│   └── useSettingsDraft.test.tsx
└── lib/
    ├── apiBase.test.ts
    ├── appMode.test.ts
    ├── categoryIcons.test.ts
    ├── constants.test.ts
    ├── getErrorMessage.test.ts
    ├── importStorage.test.ts
    └── mimeCheck.test.ts
```
