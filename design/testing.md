# Testing Strategy

For how to run tests and operational details, see [docs/development/testing.md](../docs/development/testing.md).

## Overview

Backend tests live in `backend/tests/unit/` and `backend/tests/integration/`; frontend tests are Vitest files next to the code in `frontend/src/`; Electron main-process helpers that don't import `electron` are tested with Node's built-in runner in `electron/test/` (`npm run test:electron`, TypeScript run directly via Node's type stripping); end-to-end tests are Playwright specs in `e2e/tests/`.

**No infrastructure required.** Backend tests run against a temporary SQLite database and temporary directories. LanceDB does not create files on import, so nothing is patched at import time. Tests that touch vectors use the `lancedb_service` fixture, a real LanceDB in `tmp_path` (ingest, imports API, semantic search); only the embedding model is faked. The search golden tests (`test_search_characterisation.py`) keep a deterministic `_FakeLanceDB` because they pin exact scores.

Tests marked `heavy` (real CLIP ONNX model) are excluded by default (`addopts = -m 'not heavy'` in `pyproject.toml`); run them with `-m heavy`.

## Where checks run

| Stage | Defined in | Runs |
|---|---|---|
| Pre-commit (local) | `.husky/pre-commit` | `lint-staged` on staged files |
| Pre-push (local) | `.husky/pre-push` | ruff check + format check (`backend/`, `scripts/`), pyright, backend unit tests, ESLint, Prettier check, `tsc --noEmit`, knip, Vitest, Electron `tsc`, Electron unit tests, jscpd duplication threshold |
| Pull request to `main` | `.github/workflows/ci.yml` | `backend-security` (pip-audit, bandit; blocking, accepted findings in [security.md](security.md#accepted-scanner-findings)), `backend-integration` (unit + integration tests with coverage, small ONNX model), `frontend-build` (`npm audit --omit=dev --audit-level=high`, `npm run build`), `quality` (pyright, knip, jscpd) |
| Release (manual `workflow_dispatch`) | `.github/workflows/release.yml` | full backend suite incl. heavy tests, frontend lint/tests/coverage/build, backend unit tests on Windows and macOS, Playwright E2E, Electron builds per platform with a sidecar smoke test, [packaged-app tests](#packaged-app-tests) and the [upgrade test](#upgrade-test) on Windows, the Docker image with `smoke_docker.py`, optional publish (a draft release, after every build passes and the [update metadata](#update-metadata-check) is checked). A preflight job checks the version first ([releasing.md](releasing.md)) |

CI does not run lint or unit-only jobs on PRs; the pre-push hook is relied on for those (skippable with `git push --no-verify`).

## Coverage Thresholds

- **Backend**: 40% line coverage (`pyproject.toml [tool.coverage.report] fail_under`)
- **Frontend**: 20% line coverage (`frontend/vitest.config.ts`, `@vitest/coverage-v8`)
- Ratchet these up as coverage improves.

## Shared fixtures (`backend/tests/conftest.py`)

| Fixture | Provides |
|---|---|
| `prepare_pool_fixture` (autouse) | Fresh prepare pool (2 workers) per test, shut down afterwards |
| `tmp_db` | `(engine, SessionLocal)` for a fresh SQLite DB in `tmp_path`, schema created and tag categories seeded |
| `db_session` | A session on `tmp_db`, closed after the test |
| `query_counter` | `QueryCounter` on the test engine: `with query_counter as q: ...; q.count` / `q.selects("images")`. Used in `test_query_counts.py` to pin query counts against N+1 regressions |
| `make_test_image` | Factory writing a small JPEG to a given path |
| `lancedb_service` | Real `LanceDBService` under `tmp_path` (vectors `TEST_VECTOR_SIZE` = 8 wide), installed as the module singleton so every `get_lancedb_service()` returns it |
| `shutdown_signal_cleared` (autouse) | Clears the process-wide shutdown signal, which a `TestClient` exit sets |
| `test_client` | FastAPI `TestClient` bound to `tmp_db`, with storage paths and image/thumbnail store singletons redirected to `tmp_path`, rate limiting disabled, and `settings.ingest_worker_enabled = False` |

## Conventions

### Test images

Generate programmatically with `make_test_image` or PIL/numpy (e.g. `image_bytes()` in `test_ingest_pipeline.py`). Never commit binary image blobs.

### Database isolation

Each test gets its own SQLite DB via `tmp_db`. The FastAPI lifespan sets `app.state.db_engine` to the configured database, so `test_client` sets `settings.database_url` before entering the `TestClient` and overrides `app.state.db_engine` **after** entering it.

Code that opens its own sessions from `settings.database_url` is pointed at the test DB with:

```python
monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
```

### Driving the ingest worker

Pipeline design: [ingestion.md](ingestion.md).

The background ingest thread is never started in tests. Tests construct an `IngestWorker` with a fixed `PipelineConfig`, a probe that reports no system pause, and `probe_interval=0.0`, then call `worker.drain()`, which runs batches synchronously until no work is claimable and returns the batch count:

```python
worker = IngestWorker(
    config_loader=lambda: PipelineConfig(enable_image_grid_detection=False, ingestion_batch_size=4),
    probe=lambda: None,
    probe_interval=0.0,
)
...
assert worker.drain() >= 1
```

Alongside this, ingest tests use the `lancedb_service` fixture, replace `batch_generate_clip_embeddings` with constant vectors, set `ingest_state.retry_delay` to zero, and swap `services._image_store` / `services._thumbnail_store` for `ImageStore`s under `tmp_path`. API tests additionally set `backend.pipeline.ingest_worker._worker` to the test worker so endpoints and the test share it (`test_imports_api.py`).

### Mocking the JobRunner

Endpoints that submit background jobs (model switching, some image operations) are tested with the JobRunner mocked at the import site:

```python
mock_runner = MagicMock()
monkeypatch.setattr("backend.app.api.models.get_job_runner", lambda: mock_runner)
```

### Schema drift

`backend/tests/unit/test_schema_drift.py` compares the ORM metadata against a database built by the Alembic migrations (`alembic.autogenerate.compare_metadata`). Any difference not in its `ACCEPTED` set fails, so a new column, index or constraint must be added to both the models and a migration.

### Search golden tests

`backend/tests/integration/test_search_characterisation.py` builds a deterministic library, replaces the CLIP and LanceDB services with deterministic fakes, and compares the full responses of `/search/`, `/search/groups` and `/search/facets` (ordering, totals, scores, mosaics) against `backend/tests/integration/golden/search_responses.json`. When a behaviour change is intended, regenerate and review the diff:

```bash
UPDATE_SEARCH_GOLDEN=1 uv run python -m pytest backend/tests/integration/test_search_characterisation.py
```

### Packaged-app tests

`e2e/packaged/` drives the built desktop app, not the dev servers: the windows, the backend sidecar's lifecycle, the single-instance lock, first launch, and the in-window restart when the library's folders change ([electron.md](electron.md#sidecar-lifecycle)). Build first, then run:

```bash
uv run python scripts/build/build_electron.py --dev   # unpacked app only; a full build works too
npm run test:packaged
```

Each test launches the app on a throwaway profile (its own `--user-data-dir`, so its own config and single-instance lock, and its own storage folders) and never touches a real install. `launch()` also points the updater at a closed loopback port (`SCENE_ATLAS_UPDATE_FEED`), so a test run never contacts GitHub, nor installs a real release when it quits the app. It connects over CDP (`--remote-debugging-port`): the fuses turn off `--inspect`, which Playwright's `_electron.launch` needs. Processes are found by the profile path in their command lines, so the tests can watch the sidecar exit after the app does. The Release workflow runs them on the Windows build. They also pass on Linux (run locally under WSLg, 2026-10-19, where they found that Linux notify mode never checked); macOS is untested.

### Update metadata check

electron-updater trusts the `latest.yml`, `latest-mac.yml` and `latest-linux.yml` that electron-builder writes beside the installers, so a release whose metadata doesn't match its assets breaks updates on that platform. `scripts/release/verify_update_metadata.py` runs in the Release workflow's `publish` job, after the build artifacts are downloaded and before `gh release create`, and fails the publish if any yml is missing, has the wrong `version` or no `releaseDate`, names a file that isn't an asset, gives a size or sha512 that doesn't match it, or has top-level `path`/`sha512` that differ from `files[0]`. It also fails on an asset name with a space (GitHub rewrites it), duplicate asset names across artifacts, and an `.exe` or `.dmg` without its `.blockmap`. A `.zip` isn't required for macOS: the app only notifies there until builds are signed ([electron.md](electron.md#updates)). It imports only the standard library and PyYAML, so the job runs it with `uv run --no-project --with pyyaml`. Tests: `backend/tests/unit/test_verify_update_metadata.py`.

### Upgrade test

`e2e/upgrade/` checks that updating keeps a library intact and searchable ([electron.md](electron.md#updates)). The Release workflow's Windows build packages the same code a second time as version 0.0.0 and serves the new build's `latest.yml`, installer and blockmaps (plus the old build's blockmap, so the download is differential, as from GitHub) from a local feed (`serveFeed`, with Range support). The test then:

1. installs 0.0.0 for the current user (`/S /currentuser /D=`) and starts it on a throwaway profile, with `SCENE_ATLAS_UPDATE_FEED` pointing at the feed;
2. activates the small search model (copied from the CI cache, or downloaded by the app), imports the encrypted E2E images, and makes a rename, a grid edit and a tag;
3. reads the library (every image's fields and tags, every group and its members, every thumbnail and original loading) and runs the queries (below);
4. checks for the update, waits for the download, and restarts into it: the old app must stop its backend and quit, and the installer must leave the new version in place;
5. starts the new version on the same profile and reads and queries the library again.

Then it compares the two (`checks.ts`):

| Check | Rule | Overridable |
|---|---|---|
| Library | Same images with the same fields and tags, same groups and members, the edits kept, every file loads, no query errors | **Never** |
| Exact queries | Browsing (by name), filters by type, grid, the most common authors and tags, and words-only searches for `text` and the first group names: same results in the same order | Yes |
| Semantic queries | `semantic` descriptions and `hybrid` searches (words plus meaning): same top result and, by default, 4 of the top 5 shared (per query in `queries.json`) | Yes |

Semantic results get slack because a newer onnxruntime, or DirectML against CPU, can swap near-equal scores. The derived queries come from the library before the update, so they work with whatever the image set holds.

**Accepting search changes.** A release that changes search on purpose runs the Release workflow with `accept_search_changes` and a `search_change_reason` (required). The comparison still runs, its table of changed queries goes into the job summary and the `upgrade-test-report` artifact, and the reason goes into the release notes. Library problems fail the release regardless: if a check is wrong, change it in a PR.

The report, the snapshots and the updater and backend logs are uploaded as `upgrade-test-report` on every run. The test installs into the user's profile and registry, so outside CI it only runs with `SCENE_ATLAS_UPGRADE_TEST=1`; it needs `E2E_IMAGE_KEY` and the variables listed at the top of `upgrade.spec.ts`. The pure parts (`checks.ts`, the feed server) have unit tests run by `npm run test:electron`.

**From the last release.** The workflow then runs the same test a second time from the latest published release: its installer and blockmap come from GitHub (`gh release download`), and the feed is the same with that blockmap instead of 0.0.0's. That covers the old version's own updater code and migrations on a database an older release made. It is skipped, with a notice, while no release is published, or when the build is that release's own version (a run without publish on `main` between releases); its report goes to `upgrade-report-previous/` in the same artifact.

**From GitHub, after publishing.** `UPGRADE_FROM_GITHUB=1` in place of `UPGRADE_FEED_DIR` leaves the feed override empty, so the old install updates from the real GitHub releases: a check of a published release end to end (run by hand, e.g. on Linux with an older release's AppImage). Without FUSE (WSL without `libfuse2`), set `APPIMAGE_EXTRACT_AND_RUN=1`: the runtime then doesn't set `APPIMAGE`, so `launch()` sets it to the AppImage it starts, or the app would only notify.

Not covered yet: Linux (AppImage) and macOS (notify only) in CI.

### Paths on Windows

Backend unit tests run on Windows only in the Release workflow, so Windows-only path bugs reach `main`. Two to remember: `str(engine.url)` percent-encodes a Windows path under SQLAlchemy 2.1 (use `engine.url.database`, never parse the string), and a `Path` rejoins with `\` on Windows, so archive names are built with `PurePosixPath`.

## What to test when adding new features

| Change | Tests to add/update |
|---|---|
| New parser rule | `unit/test_parser.py` |
| New Pydantic schema | `unit/test_schemas.py` -- defaults, round-trip, serialization |
| New model column / index | Alembic migration; `unit/test_schema_drift.py` must stay green |
| New API endpoint | New or existing file in `integration/` using `test_client` |
| Ingest pipeline change | `integration/test_ingest_pipeline.py` (worker + `drain()`), `unit/test_ingest_state.py` for state transitions |
| Search behaviour change | `integration/test_search_endpoint.py`; regenerate the golden file if responses change intentionally |
| New list/search query | `integration/test_query_counts.py` to pin the query count |
| New user-facing flow | `e2e/tests/` -- Playwright spec exercising the UI flow |
| New surface or dialog | Add it to `e2e/tests/accessibility.spec.ts` (axe scan in both themes) |
| Electron main process, sidecar lifecycle, packaging | `electron/test/` for pure helpers; `e2e/packaged/` for behaviour of the built app |

## Known quirks

- **TestClient lifespan override.** The FastAPI lifespan sets `app.state.db_engine` from settings. Fixtures override it **after** `TestClient.__enter__()`.
- **Store singletons.** `services._image_store` / `services._thumbnail_store` may already be cached at the real library path by an earlier test; fixtures replace them rather than relying on settings alone.
- **Exit code 134 in CI.** Native libraries can abort during interpreter shutdown after all tests pass; `ci.yml` and the integration step in `release.yml` tolerate exit code 134.
