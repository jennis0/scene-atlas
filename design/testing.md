# Testing Strategy

For how to run tests, test file listings, and operational details, see [docs/testing.md](../docs/testing.md).

## Overview

The test suite covers the ingestion pipeline end-to-end: parsing, pipeline functions, API endpoints, and the critical metadata round-trip that ensures user edits survive to the database.

**No infrastructure required.** All tests run without external services. Qdrant's `QdrantClient` is mocked at import time to prevent creating local DB files during tests.

## CI/CD Tiered Strategy

```
Tier 1 -- Pre-commit (local):  lint-staged (ruff + eslint + prettier on staged files)
Tier 2 -- Every push & PR:     lint + format + unit tests + frontend tests + build + backend-integration + frontend-coverage
Tier 3 -- Push to main:        + heavy tests (CLIP) + E2E (Playwright)
Tier 4 -- Version tags (v*):   gate check + multi-platform electron build + release
```

**Note:** `backend-integration` and `frontend-coverage` run on every push (Tier 2), not just on main. A `backend-unit-cross-platform` job also runs on every push, executing unit tests on Windows and macOS in addition to Linux.

### GitHub Actions Workflows

- `.github/workflows/ci.yml` -- Tiers 1-3 (backend-lint -> backend-unit -> backend-integration + backend-heavy + e2e, frontend-lint -> frontend-test/build -> frontend-coverage)
- `.github/workflows/electron-build.yml` -- Tier 4 (gate job -> matrix build for Windows/macOS/Linux)

## Coverage Thresholds

- **Backend**: 40% line coverage (measured via `pytest-cov`, `pyproject.toml [tool.coverage.report]`)
- **Frontend**: 20% line coverage (measured via `@vitest/coverage-v8`, `vitest.config.ts`)
- Thresholds should be ratcheted up as test coverage improves

## Conventions

### Test images

Generate programmatically -- never commit binary blobs:

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
- `generate_clip_embedding` -> dummy 512-dim vector
- `qdrant_service.add_image_embedding` -> returns True
- `generate_thumbnails` -> returns key dict without writing files
- `extract_dominant_colors` -> returns two dummy colors

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
| New parser rule | `test_parser.py` -- add case for parse() and/or group_files() |
| New Pydantic schema | `test_schemas.py` -- defaults, round-trip, serialization |
| New API endpoint | New file in `integration/` -- mock JobRunner, use TestClient |
| New pipeline logic | `integration/` -- call function directly, mock heavy services |
| New metadata field | `test_metadata_roundtrip.py` -- verify it survives the round-trip |
| New user-facing flow | `e2e/tests/` -- add Playwright spec exercising the UI flow |

## Known quirks

- **Qdrant mocking must happen before import.** `conftest.py` patches `qdrant_client.QdrantClient` before `backend.app.services` loads, because `QdrantService.__init__()` creates an embedded local DB on disk. The lazy singleton (`get_qdrant_service()`) defers creation, but the QdrantClient class still needs to be mocked before any test triggers it.
- **TestClient lifespan override.** The FastAPI lifespan sets `app.state.db_engine` to production. Fixtures must override it **after** `TestClient.__enter__()`, not before.
