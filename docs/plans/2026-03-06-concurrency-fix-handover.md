# Handover: Concurrency Fix — `def` Endpoints + Admission Control + Stress Test Fixes

**Date**: 2026-03-06
**Status**: Ready for implementation
**Branch**: Create `feature/concurrency-fix` worktree

---

## Problem

Stress tests fail under heavy concurrency (100 concurrent imports). Root causes:

1. **Event-loop starvation**: All 50+ FastAPI endpoints are `async def` but call synchronous SQLAlchemy directly on the event loop. Under concurrent load, sync DB calls block the event loop thread, preventing it from accepting/responding to other requests.
2. **GIL thrashing**: The `analyse_staged` endpoint launches `asyncio.to_thread(analyse_upload)`. With 100 concurrent requests, 100 threads fight for the GIL, starving the event loop so severely that clients get `ReadTimeout`.
3. **No idempotency on confirm-all**: Multiple concurrent `confirm-all` requests all succeed — there's no status guard checking whether the job has already been confirmed.
4. **Empty error messages**: `ReadTimeout` exceptions have `str()` == `""`, so stress test failure messages show "Job 0 raised:" with no useful information.

## Design Decision: Why Not Async SQLAlchemy

An async SQLAlchemy migration was designed, reviewed, and rejected. Key reasoning:

- `aiosqlite` wraps sync `sqlite3` in a background thread — functionally identical to FastAPI's `run_in_threadpool` for `def` endpoints
- The migration would require: ~400 lines of query rewrites (103 sites), dual sync/async service functions, `aiosqlite` dependency, global `lazy="selectin"` with over-fetching side effects
- Module-level `asyncio.Semaphore` breaks on Python 3.12+ / Windows
- Zero practical benefit on SQLite; only worthwhile when Postgres is added

The simpler fix: change `async def` to `def` on DB-touching endpoints. FastAPI routes `def` handlers through a threadpool automatically, freeing the event loop with no code changes beyond removing the `async` keyword.

---

## Implementation Plan

### Phase 1: Stress Test Error Reporting

**File**: `stress_tests/scenarios.py`

Fix 7 locations where generic `except Exception as exc` formatting produces empty messages for `ReadTimeout`. Each has a slightly different format — find them by searching for `except Exception as exc` and add `{type(exc).__name__}: ` before `{exc}`:

| Approx. line | Current format | Change to |
|------|---------------|-----|
| ~307 | `f"Job {job_idx} raised: {exc}"` | `f"Job {job_idx} raised {type(exc).__name__}: {exc}"` |
| ~810 | `f"Sequential {path.name}: {exc}"` | `f"Sequential {path.name} {type(exc).__name__}: {exc}"` |
| ~838 | `f"Concurrent upload {idx}: {exc}"` | `f"Concurrent upload {idx} {type(exc).__name__}: {exc}"` |
| ~1061 | `f"Job {idx}: {exc}"` | `f"Job {idx} {type(exc).__name__}: {exc}"` |
| ~1168 | `f"Unexpected error: {exc}"` | `f"Unexpected error {type(exc).__name__}: {exc}"` |
| ~1233 | `f"Job {job_idx}: {exc}"` | `f"Job {job_idx} {type(exc).__name__}: {exc}"` |
| ~1301 | `f"Job {job_idx}: {exc}"` | `f"Job {job_idx} {type(exc).__name__}: {exc}"` |

**Verify**: Run `uv run python -m stress_tests run --scenario concurrent_imports --quick` and confirm exceptions now show their type name.

---

### Phase 2: Convert `async def` to `def` on DB-touching Endpoints

**Principle**: FastAPI runs `def` route handlers in a threadpool via `run_in_threadpool`, freeing the event loop. No query rewrites needed — `db.query(...)` syntax stays identical.

**CRITICAL — audit each endpoint for `await` before converting**. Some endpoints have async I/O that is NOT SQLAlchemy-related. Converting those to `def` would break them silently.

#### Endpoints that MUST stay `async def`:

| Endpoint | File | Reason |
|----------|------|--------|
| `analyse_staged` | `backend/app/api/imports.py` | Uses `await asyncio.to_thread(analyse_upload, ...)` |
| `confirm_all_groups` | `backend/app/api/imports.py` | Will use `await` for admission semaphore (Phase 3) |
| `upload_batch` | `backend/app/api/imports.py` | Uses `await _save_files_to_staging()` which calls `await upload_file.read()` — genuine Starlette async I/O |
| `jobs.py` endpoints | `backend/app/api/jobs.py` | Already pure async with no DB — leave as-is |

#### Files to convert (all other endpoints become `def`):

| Router file | Action |
|---|---|
| `backend/app/api/settings.py` | `async def` -> `def` on all endpoints |
| `backend/app/api/images.py` | `async def` -> `def` on all endpoints |
| `backend/app/api/groups.py` | `async def` -> `def` on all endpoints |
| `backend/app/api/tags.py` | `async def` -> `def` on all endpoints |
| `backend/app/api/search.py` | `async def` -> `def` on all endpoints |
| `backend/app/api/export.py` | `async def` -> `def` on all endpoints |
| `backend/app/api/system.py` | `async def` -> `def` on all endpoints (except health check if it has no DB) |
| `backend/app/api/imports.py` | Audit individually. Convert DB-only endpoints to `def`. Keep `upload_batch`, `analyse_staged`, `confirm_all_groups` as `async def`. |

#### Process for each file:
1. Open the file, find each `async def` endpoint
2. Search the function body for `await`. If it awaits anything other than sync DB calls, keep as `async def`
3. Remove `async` keyword. No other changes needed.
4. `ruff check` will catch any remaining `await` inside a non-async function

**Verify**: `uv run pytest` after each file. No query changes = minimal regression risk.

---

### Phase 3: Admission Control Semaphore

#### 3.1 Add `max_concurrent_heavy_requests` setting

**Files**: `backend/app/services/app_settings.py` + `backend/app/models/database.py` (seed data)

Add a new `max_concurrent_heavy_requests` field to `AppSettings` with default value `4`.

This is intentionally separate from `max_concurrent_prepare` (which controls per-job image processing parallelism inside the pipeline, default 8). The new setting controls how many heavy HTTP requests (`analyse`, `confirm-all`) can execute concurrently at the API layer.

#### 3.2 Create semaphore in app lifespan

**File**: `backend/app/main.py`

In the `lifespan` function, after reading settings from DB, create and store the semaphore:

```python
app.state.heavy_op_semaphore = asyncio.Semaphore(
    settings_from_db.max_concurrent_heavy_requests
)
```

**Do NOT create the semaphore at module level.** `asyncio.Semaphore()` created before an event loop exists raises errors on Python 3.12+ and on Windows (ProactorEventLoop).

#### 3.3 Create FastAPI dependency

**File**: `backend/app/api/dependencies.py`

```python
async def acquire_heavy_op(request: Request):
    """Admission control — limits concurrent heavy operations."""
    semaphore = request.app.state.heavy_op_semaphore
    await semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()
```

#### 3.4 Apply to heavy endpoints

**File**: `backend/app/api/imports.py`

Add `_admission: None = Depends(acquire_heavy_op)` to:
- `analyse_staged` — gates concurrent `asyncio.to_thread(analyse_upload)` calls
- `confirm_all_groups` — gates concurrent job submissions to the JobRunner

When the semaphore is full, additional requests await it. The event loop stays responsive (Phase 2 moved other endpoints off the loop), and clients see slow responses rather than timeouts.

#### 3.5 Write status guards on confirm endpoints

**These do NOT exist yet — write from scratch.**

**File**: `backend/app/api/imports.py`

In `confirm_all_groups`, immediately after the job DB lookup:
```python
if job.status != "staging":
    raise HTTPException(
        status_code=409,
        detail=f"Job is already {job.status}, cannot confirm again",
    )
```

In `confirm_import`, immediately after the job DB lookup:
```python
if job.all_confirmed:
    raise HTTPException(
        status_code=409,
        detail="Job has already been fully confirmed via confirm-all",
    )
```

Without these guards, the `endpoint_spam` stress test sub-test 4 fails — multiple concurrent confirms all succeed when only one should.

**Verify**: `uv run pytest`

---

### Phase 4: Stress Test Timeout Adjustments

**These changes need to be written** (they are NOT already in the file).

**File**: `stress_tests/scenarios.py`

With admission control, requests queue behind the semaphore instead of all executing at once. Individual requests take longer but actually complete instead of timing out.

- `ImportFlow.analyse()` method (~line 131): add `timeout=300.0` to the `self._request()` call
- `ImportFlow.confirm_all()` method (~line 165): add `timeout=300.0` to the `self._request()` call
- Check `wait_for_terminal()` — its default timeout of 180s may need increasing to 300s for the full 100-job run

**Verify**: `uv run python -m stress_tests run --quick` — all scenarios pass.

---

### Phase 5: Cleanup and Validation

1. `uv run ruff check backend/ stress_tests/ && uv run ruff format backend/ stress_tests/`
2. `uv run pytest` — full pass
3. `uv run python -m stress_tests run --quick` — all scenarios pass
4. `uv run python -m stress_tests run --scenario concurrent_imports` — full 100-job run passes
5. `uv run python -m stress_tests run --scenario endpoint_spam` — confirm-all idempotency passes
6. Add a design doc in `design/` noting the concurrency architecture decision and rationale
7. Commit with message like: `fix: concurrency — def endpoints, admission control, stress test fixes`

---

## Key Files Reference

| File | Change |
|------|--------|
| `stress_tests/scenarios.py` | Error reporting (7 locations) + timeout increases |
| `backend/app/api/settings.py` | `async def` -> `def` |
| `backend/app/api/images.py` | `async def` -> `def` |
| `backend/app/api/groups.py` | `async def` -> `def` |
| `backend/app/api/tags.py` | `async def` -> `def` |
| `backend/app/api/search.py` | `async def` -> `def` |
| `backend/app/api/export.py` | `async def` -> `def` |
| `backend/app/api/system.py` | `async def` -> `def` (most endpoints) |
| `backend/app/api/imports.py` | Mixed: `def` for DB-only, keep `async def` on 3 endpoints, add semaphore + status guards |
| `backend/app/main.py` | Create semaphore in lifespan |
| `backend/app/api/dependencies.py` | Add `acquire_heavy_op` dependency |
| `backend/app/models/database.py` | Seed `max_concurrent_heavy_requests` |
| `backend/app/services/app_settings.py` | Add `max_concurrent_heavy_requests` to AppSettings |

## Risks and Gotchas

| Risk | Severity | Mitigation |
|------|----------|-----------|
| `def` endpoints run in limited threadpool | Low | Starlette default is 40 threads — sufficient for 5-50 users. Tune via `anyio.to_thread.current_default_thread_limiter().total_tokens` at startup if needed. |
| Endpoint with hidden `await` breaks on `def` | **Medium** | **Audit each endpoint for `await` before converting.** Known async: `upload_batch`, `analyse_staged`, `confirm_all_groups`. `ruff` catches `await` in non-async functions at lint time. |
| Confirm-all race window | Low | Status guard + semaphore make the window very small. SQLite WAL ensures committed writes are visible to subsequent readers. Acceptable for pre-release. |
| Pipeline code affected | None | Pipeline uses its own `pipeline_db()` context manager — completely independent of endpoint code. |

## Future: Async SQLAlchemy

When Postgres is added to the roadmap, a proper async migration becomes worthwhile:
- `create_async_engine` with `asyncpg` driver gives true non-blocking I/O (unlike `aiosqlite` which is thread-wrapped sync)
- Convert `def` endpoints back to `async def` with `AsyncSession`
- The admission control semaphore and status guards from this work carry forward unchanged
