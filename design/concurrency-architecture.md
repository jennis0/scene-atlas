# Concurrency Architecture

**Date**: 2026-03-06

## Problem

Under heavy concurrency (100+ concurrent imports), the server becomes unresponsive:
- All 50+ FastAPI endpoints were `async def` but called synchronous SQLAlchemy directly, blocking the event loop
- `analyse_staged` launched unbounded `asyncio.to_thread()` calls, causing GIL thrashing
- No idempotency guard on `confirm-all` — concurrent confirms all succeeded

## Solution

### 1. `def` Endpoints (Event Loop Freedom)

All DB-touching endpoints converted from `async def` to `def`. FastAPI automatically runs `def` route handlers in a threadpool via `run_in_threadpool`, freeing the event loop to handle other requests.

**Endpoints kept as `async def`:**
- `upload_batch` — uses `await upload_file.read()` (Starlette async I/O)
- `analyse_staged` — uses `await asyncio.to_thread(analyse_upload)`
- `confirm_all_groups` — uses `await` for admission control semaphore

### 2. Admission Control Semaphore

A `asyncio.Semaphore(max_concurrent_heavy_requests)` (default 4) gates concurrent heavy operations. Applied as a FastAPI dependency to `analyse_staged` and `confirm_all_groups`.

Created in the app lifespan (not at module level) to avoid Python 3.12+ / Windows event loop issues.

**Setting**: `max_concurrent_heavy_requests` in AppSettings (default 4). Note: changing this setting requires a restart — the semaphore is created once at startup.

### 3. Status Guards

`confirm_all_groups` now rejects requests unless `job.status == "staging"`, returning HTTP 409. This prevents double-confirm races.

## Why Not Async SQLAlchemy

`aiosqlite` wraps sync `sqlite3` in a background thread — functionally identical to what FastAPI's threadpool does for `def` endpoints. The migration would require ~400 lines of query rewrites across 103 sites, with zero practical benefit on SQLite. Worthwhile when Postgres is added.

## Key Files

| File | Change |
|------|--------|
| `backend/app/api/*.py` | `async def` → `def` on DB-touching endpoints |
| `backend/app/api/imports.py` | Semaphore dependency + status guard on confirm-all |
| `backend/app/api/dependencies.py` | `acquire_heavy_op` dependency |
| `backend/app/main.py` | Semaphore creation in lifespan |
| `backend/app/models/schemas.py` | `max_concurrent_heavy_requests` setting |
| `stress_tests/scenarios.py` | Error reporting + timeout adjustments |
