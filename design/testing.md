# Testing Strategy

## Overview

The test suite covers the ingestion pipeline end-to-end: parsing, pipeline functions, API endpoints, and the critical metadata round-trip that ensures user edits survive to the database.

**No infrastructure required.** All tests run without external services. Qdrant's `QdrantClient` is mocked at import time to prevent creating local DB files during tests.

## CI/CD Pipeline

### Tiered Test Strategy

```
Tier 1 — Pre-commit (local):  lint-staged (ruff + eslint + prettier on staged files)
Tier 2 — Every push & PR:     lint + format + unit tests + frontend tests + build
Tier 3 — Push to main:        + integration tests + heavy tests (CLIP) + coverage reporting
Tier 4 — Version tags (v*):   gate check + multi-platform electron build + release
```

### GitHub Actions Workflows

- `.github/workflows/ci.yml` — Tiers 1-3 (backend-lint → backend-unit → backend-integration + backend-heavy, frontend-lint → frontend-test/build → frontend-coverage)
- `.github/workflows/electron-build.yml` — Tier 4 (gate job → matrix build for Windows/macOS/Linux)

### Coverage Thresholds

- **Backend**: 40% line coverage (measured via `pytest-cov`, `pyproject.toml [tool.coverage.report]`)
- **Frontend**: 10% line coverage (measured via `@vitest/coverage-v8`, `vitest.config.ts`)
- Thresholds should be ratcheted up as test coverage improves

### Local Development

```bash
# Pre-commit hooks (auto-installed via `npm install` → husky prepare)
# Runs lint-staged on commit: ruff for .py, eslint+prettier for .ts/.tsx

# Manual checks
make check          # lint + format-check (both backend + frontend)
make test           # unit tests + frontend tests (fast, ~15s)
make test-all       # unit + integration + frontend (~30s)
make test-heavy     # CLIP model tests (downloads ~600MB model on first run)
make test-cov       # full suite with coverage reporting
make lint-fix       # auto-fix all lint + format issues
```

## Running Tests

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

# Heavy tests (real CLIP model — ~600MB download on first run, cached after)
uv run python -m pytest -m heavy -v

# Run everything including heavy
uv run python -m pytest -m '' -v
```

## Heavy Tests (CLIP)

Tests marked with `@pytest.mark.heavy` load the real CLIP model (~600 MB) and run real inference. They are **excluded by default** via `addopts = "-m 'not heavy'"` in pyproject.toml.

**Model caching:**
- HuggingFace Transformers caches models at `~/.cache/huggingface/hub/`
- Locally, the model is downloaded once and reused across runs
- On GitHub Actions, the cache is persisted between runs via `actions/cache@v4` keyed on `backend/app/config.py` (which contains the model name)
- First CI run downloads the model (~600 MB); subsequent runs restore from cache

**Test fixture:** The `clip_service` fixture is `session`-scoped and also primes the module-level singleton, so both direct `CLIPService` usage and `get_clip_service()` code paths work.

## Three-Layer Structure

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
│   └── test_system_info.py        # dir_size utility
├── integration/                   # Real SQLite DB, mocked CLIP/Qdrant
│   ├── test_metadata_roundtrip.py # User edits survive to DB (highest priority)
│   ├── test_analyse_upload.py     # analyse_upload (grouping + thumbnails)
│   ├── test_process_single.py     # process_single_image (both modes)
│   ├── test_process_import_group.py # process_import_group + process_import_job
│   ├── test_upload_endpoint.py    # POST /imports/upload
│   ├── test_confirm_endpoint.py   # POST /imports/{id}/confirm
│   ├── test_preview_endpoint.py   # GET /imports/{id}/preview/{path}
│   ├── test_search_endpoint.py    # GET /api/v1/search/ + facets
│   ├── test_images_endpoint.py    # GET/PATCH/DELETE /api/v1/images/ + scenes + file serving
│   ├── test_export_endpoint.py    # GET /api/v1/export/library (ZIP structure + metadata)
│   ├── test_system_admin.py       # GET /api/v1/system/ endpoints
│   └── test_clip_heavy.py         # Real CLIP model tests (marked @heavy, excluded by default)
├── e2e/                           # Full infrastructure tests (future)
└── legacy/                        # Old manual scripts — delete as replaced

frontend/src/
├── components/
│   ├── DesktopGate.test.tsx
│   └── SystemInfoDialog.test.tsx
├── hooks/
│   └── useJobPolling.test.ts
└── lib/
    └── appMode.test.ts
```

## Conventions

### Test images

Generate programmatically — never commit binary blobs:

```python
@pytest.fixture
def make_test_image():
    def _make(path, width=20, height=20, color=(100, 150, 200)):
        path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (width, height), color)
        img.save(path, format="JPEG", quality=70)
        return path
    return _make
```

### Database isolation

Each test gets a fresh SQLite DB via `tmp_db` fixture. The `test_client` fixture overrides `app.state.db_engine` **after** the TestClient enters (since the lifespan sets it to production).

### Mocking heavy services

Use the `mock_heavy_services` fixture for any test that calls pipeline functions. It mocks:
- `generate_clip_embedding` → dummy 512-dim vector
- `qdrant_service.add_image_embedding` → returns True
- `generate_thumbnails` → returns key dict without writing files
- `extract_dominant_colors` → returns two dummy colors

For integration tests that also need an `ImageStore`, add:
```python
@pytest.fixture
def _patch_image_store(monkeypatch, tmp_path):
    from backend.app.services.image_store import ImageStore
    store = ImageStore(tmp_path / "store")
    monkeypatch.setattr("backend.pipeline.ingestion.get_image_store", lambda: store)
    return store
```

### Mocking the JobRunner (endpoint tests)

Endpoint tests mock the JobRunner since they don't call pipeline functions directly:
```python
mock_runner = MagicMock()
monkeypatch.setattr("backend.app.api.imports.get_job_runner", lambda: mock_runner)
```

### Patching the DB for pipeline tests

Pipeline functions read `settings.database_url` internally. Override it to point at the test DB:
```python
monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
```

## What to test when adding new features

| Change | Tests to add/update |
|---|---|
| New parser rule | `test_parser.py` — add case for parse() and/or group_files() |
| New Pydantic schema | `test_schemas.py` — defaults, round-trip, serialization |
| New API endpoint | New file in `integration/` — mock JobRunner, use TestClient |
| New pipeline logic | `integration/` — call function directly, mock heavy services |
| New metadata field | `test_metadata_roundtrip.py` — verify it survives the round-trip |

## Known quirks

- **Qdrant mocking must happen before import.** `conftest.py` patches `qdrant_client.QdrantClient` before `backend.app.services` loads, because `QdrantService.__init__()` creates an embedded local DB on disk. The lazy singleton (`get_qdrant_service()`) defers creation, but the QdrantClient class still needs to be mocked before any test triggers it.
- **TestClient lifespan override.** The FastAPI lifespan sets `app.state.db_engine` to production. Fixtures must override it **after** `TestClient.__enter__()`, not before.

## Future: Real Qdrant in integration tests

Since Qdrant now runs in embedded local mode (`QdrantClient(path=...)`), we could use a real instance pointed at `tmp_path` in integration tests. This would test real vector search behavior (add + query roundtrip) and remove the fragile import-order mocking. Still fast since it's just local files with no network.
