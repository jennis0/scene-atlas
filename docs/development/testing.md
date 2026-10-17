# Running Tests

For testing strategy, conventions, and guidelines on what to test, see [design/testing.md](../../design/testing.md).

For stress testing the import pipeline, see [stress-testing.md](stress-testing.md).

## Where Tests Run

| Where | When | What |
|-------|------|------|
| Pre-commit hook | `git commit` | lint-staged: ruff fix/format on staged `backend/` and `scripts/` Python, ESLint + Prettier on staged `frontend/src` files, Prettier on `electron/src` |
| Pre-push hook (`.husky/pre-push`) | `git push` | ruff check + format check (`backend/`, `scripts/`), `pytest backend/tests/unit/`, ESLint, `prettier --check src/`, `tsc --noEmit` (frontend + Electron), vitest |
| CI (`.github/workflows/ci.yml`) | Pull requests to `main` | pip-audit + bandit, backend unit + integration tests with coverage (small model), frontend `npm run build` |
| Release (`.github/workflows/release.yml`) | Manual | Everything above plus heavy tests, frontend coverage, unit tests on Windows and macOS, Playwright E2E, then Electron builds |

Run `npm install` at the repository root to install the Husky hooks. If you only run `uv sync`, no hooks are installed and nothing runs before CI.

## Quick Reference

```bash
# Backend unit tests (what pre-push runs)
uv run python -m pytest backend/tests/unit -v

# Unit + integration (integration needs the small model: make ensure-model)
EMBEDDING_MODEL=small uv run python -m pytest backend/tests/unit backend/tests/integration -v

# A single file (fast feedback loop)
uv run python -m pytest backend/tests/unit/test_parser.py -v

# Frontend tests
cd frontend && npx vitest run

# Frontend tests with watch mode
cd frontend && npx vitest

# Heavy tests (real CLIP ONNX model, setup via scripts/models/setup_models.py)
uv run python -m pytest -m heavy -v

# Run everything including heavy
uv run python -m pytest -m '' -v

# E2E tests (Playwright starts an isolated backend; stop any dev backend on :8000 first)
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
make test-e2e       # Playwright E2E tests (Chromium)
make test-e2e-ui    # Playwright interactive UI mode (for debugging)
make test-cov       # full suite with coverage reporting
make lint-fix       # auto-fix all lint + format issues
```

## Integration Tests (CLIP model required)

Integration tests and heavy tests need a real ONNX model. `make test-integration` and `make test-heavy` automatically download the `small` model (~250 MB) on first run via `make ensure-model`. The model is cached locally and only downloaded once.

```bash
make ensure-model       # download small model if not present
make test-integration   # integration tests with EMBEDDING_MODEL=small
make test-heavy         # heavy tests with real CLIP inference
```

## Heavy Tests (CLIP)

Tests marked with `@pytest.mark.heavy` load the real CLIP ONNX model and run real inference. They are **excluded by default** via `-m 'not heavy'` in the pytest `addopts` in pyproject.toml. Currently only `test_clip_heavy.py` uses this marker.

**Model caching:**
- ONNX models are cached in CI via `actions/cache@v4` keyed on `backend/app/services/model_registry.py`
- On a cache miss, CI downloads the `small` model from HuggingFace with `scripts/models/setup_models.py` (no export in CI)

**Test fixture:** The `clip_service` fixture is `session`-scoped and also primes the module-level singleton, so both direct `CLIPService` usage and `get_clip_service()` code paths work.

## ONNX Model Assessment

Quality evaluation is integrated into `scripts/models/export_model_onnx.py` via the `--image-dir` flag. When provided, the export script runs a comprehensive quality assessment using the torch model (still loaded from the export phase) as reference.

**When it runs:**
- Locally: `uv run python scripts/models/export_model_onnx.py <model> --image-dir /path/to/images`, where `<model>` is a name from `backend/app/services/model_registry.py` (`small`, `medium`, `large`). The `make evaluate-onnx` target still passes the old `clip-vit-b-32` name and `data/store/images` path.
- Not in CI (requires real images and the torch model)

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

Playwright tests validate critical user flows in a real browser against the full stack (real backend, real frontend, real CLIP model). They run in the release workflow, not on pull requests.

**Architecture:**
- Located in `e2e/` at project root (not inside `frontend/`) -- tests exercise the full stack
- Dual webServer config: Playwright starts both backend and frontend automatically
- Real CLIP model (no mocking) -- loads in a background thread, server responds immediately
- Test data seeded via the imports API (create → manifest → seal → per-file `PUT`, then poll until `completed`) using real encrypted fixture images (decrypted at runtime from Git LFS; needs `E2E_IMAGE_KEY`)
- Isolated storage: each run gets a fresh `e2e/.tmp-data/run-XXXXXX/` and the backend is started with `APP_DATA_DIR` / `IMAGE_LIBRARY_DIR` pointing into it, so E2E never touches your `./data` or `./images`. The previous run's directory is kept for debugging and deleted when the next run starts
- The ONNX model is linked into the run directory from `data/models/` (where `setup_models.py` and CI put it); set `E2E_MODELS_DIR` to use another models directory
- Serial execution (`workers: 1`) -- tests share backend state
- Chromium only in CI; Firefox/WebKit available locally via `--project` flag

**Key files:**
- `e2e/playwright.config.ts` -- Dual webServer, serial execution, CI/local reporter config
- `e2e/fixtures/base.ts` -- Worker-scoped auto fixture that decrypts real images and seeds via API
- `e2e/helpers/seed.ts` -- Seeds images via the imports API and polls `GET /imports/{id}` until done
- `e2e/helpers/isolation.ts` -- Creates the per-run storage directory and exports `APP_DATA_DIR` / `IMAGE_LIBRARY_DIR`
- `e2e/helpers/decrypt-fixtures.ts` -- Decrypts `e2e-images.zip.enc` (Git LFS) for CI and local dev

**`reuseExistingServer`:** The backend is never reused: a running dev backend uses your real library, and the seed would import into it. Stop any backend on port 8000 before running E2E (the frontend proxies to that port, so E2E can't use another). A running frontend dev server is reused locally; in CI both servers start fresh.

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
├── conftest.py            # Shared fixtures, LanceDB/CLIP mocking
├── fixtures/              # Fixture notes (README.md)
├── unit/                  # Pure logic: parser, schemas, ingest state machine, error
│                          # classifier, memory budget, image hashes, grid detector,
│                          # search/FTS, image store, maintenance, config, ORT providers,
│                          # schema drift (ORM vs Alembic), ...
├── integration/           # Real SQLite DB, mocked or real CLIP:
│   ├── test_imports_api.py         # Import job API (manifest, seal, content PUT, actions)
│   ├── test_ingest_pipeline.py     # IngestWorker end to end
│   ├── test_search_endpoint.py     # Search + facets
│   ├── test_search_characterisation.py  # Ranking snapshots (golden/search_responses.json)
│   ├── test_query_counts.py        # N+1 query guards
│   ├── test_images_endpoint.py, test_groups_endpoint.py, test_tags_endpoint.py,
│   ├── test_export_endpoint.py, test_models_api.py, test_system_*.py,
│   ├── test_health_endpoint.py, test_rate_limits.py, test_backup_restore.py
│   └── test_clip_heavy.py          # Real CLIP model (marked heavy, excluded by default)
├── test_prepare_pool.py   # Outside pytest testpaths: run only when targeted explicitly,
└── test_seed_settings.py  # never by a bare `pytest`, pre-push, or CI

e2e/                       # Playwright (full stack, real browser)
├── playwright.config.ts   # Dual webServer (backend + frontend), serial
├── fixtures/              # base.ts seed fixture, e2e-images.zip.enc (Git LFS)
├── helpers/               # actions.ts, config.ts, decrypt-fixtures.ts, seed.ts
└── tests/                 # 10 *.spec.ts files listed above

frontend/src/              # Vitest, colocated *.test.ts(x) files
├── components/            # ActivityDock, DesktopGate, EditGroupDialog, LibraryInfoDialog,
│                          # import/*, imports/imports.test.tsx
├── contexts/              # ThemeContext
├── hooks/                 # useEditGroupOperations, useFileEditing, useGalleryDialogs,
│                          # useGallerySearch, useJobPolling, useSettingsDraft
└── lib/                   # apiBase, appMode, categoryIcons, constants, getErrorMessage,
                           # import/ImportManager.test.ts
```

List the current files with `ls backend/tests/unit backend/tests/integration` and `find frontend/src -name "*.test.ts*"`.
