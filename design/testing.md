# Testing Strategy

## Overview

The test suite covers the ingestion pipeline end-to-end: parsing, flow orchestration, API endpoints, and the critical metadata round-trip that ensures user edits survive to the database.

**No infrastructure required.** All tests run without Docker, Prefect server, or Qdrant. Qdrant is mocked at import time; Prefect flows use ephemeral in-memory mode.

## Running Tests

```bash
# All fast tests (unit + integration, ~20s)
uv run pytest backend/tests/unit backend/tests/integration -v

# Just parser tests (fastest feedback loop, ~5s)
uv run pytest backend/tests/unit/test_parser.py -v

# Just the critical round-trip test
uv run pytest backend/tests/integration/test_metadata_roundtrip.py -v
```

## Three-Layer Structure

```
backend/tests/
├── conftest.py              # Shared fixtures, Qdrant/Prefect mocking
├── unit/                    # Pure logic, no DB, no filesystem side effects
│   ├── test_parser.py       # BattlemapParser.parse() and group_files()
│   ├── test_schemas.py      # Pydantic model validation and round-trips
│   └── test_thumbnail_names.py  # Preview thumbnail filename consistency
├── integration/             # Real SQLite DB, mocked CLIP/Qdrant/Prefect
│   ├── test_metadata_roundtrip.py  # User edits survive to DB (highest priority)
│   ├── test_analyse_flow.py        # analyse_upload flow (grouping + thumbnails)
│   ├── test_process_single.py      # process_single_image (both modes)
│   ├── test_upload_endpoint.py     # POST /imports/upload
│   ├── test_confirm_endpoint.py    # POST /imports/{id}/confirm
│   └── test_preview_endpoint.py    # GET /imports/{id}/preview/{path}
├── e2e/                     # Full infrastructure tests (future)
└── legacy/                  # Old manual scripts — delete as replaced
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

Use the `mock_heavy_services` fixture for any test that calls Prefect flows. It mocks:
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
    monkeypatch.setattr("backend.flows.ingestion.get_image_store", lambda: store)
    return store
```

### Mocking Prefect deployments (endpoint tests)

Endpoint tests mock `run_deployment` since they don't call flows directly:
```python
mock_run_deployment = AsyncMock(return_value=mock_flow_run)
monkeypatch.setattr("backend.app.api.imports.run_deployment", mock_run_deployment)
```

### Patching the DB for flow tests

Flows read `settings.database_url` internally. Override it to point at the test DB:
```python
monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
```

## What to test when adding new features

| Change | Tests to add/update |
|---|---|
| New parser rule | `test_parser.py` — add case for parse() and/or group_files() |
| New Pydantic schema | `test_schemas.py` — defaults, round-trip, serialization |
| New API endpoint | New file in `integration/` — mock Prefect, use TestClient |
| New flow logic | `integration/` — call flow directly, mock heavy services |
| New metadata field | `test_metadata_roundtrip.py` — verify it survives the round-trip |

## Known quirks

- **Qdrant mocking must happen before import.** `conftest.py` patches `qdrant_client.QdrantClient` before `backend.app.services` loads, because `qdrant_service.py` creates a global `QdrantService()` instance at import time.
- **Prefect ephemeral shutdown noise.** Prefect's ephemeral server logs a "Stopping temporary server" error during interpreter shutdown (Rich console already closed). This is cosmetic and doesn't affect test results.
- **TestClient lifespan override.** The FastAPI lifespan sets `app.state.db_engine` to production. Fixtures must override it **after** `TestClient.__enter__()`, not before.
