# Security Phase 2 — Handover

**Date:** 2026-03-04
**Branch:** `feature/security-phase-2`
**Worktree:** `.worktrees/security-phase-2`
**HEAD:** `204fc47`
**Tests:** 427 unit tests passing (0 failures)

---

## What Has Been Done

The following tasks from `docs/plans/2026-03-03-security-phase-2.md` are **complete and committed**:

| # | Task | Commit |
|---|------|--------|
| 1 | Security headers middleware | `c2230f6` |
| 2 | AUTH_TOKEN config setting + `.env.example` | `5f2603f` |
| 3 | `verify_auth` FastAPI dependency | `2ad8306` |
| 5 | `generate_token` convenience script | `204fc47` (review fix batch) |
| — | Code review fixes (see below) | `204fc47` |

### Code review fixes applied (all in `204fc47`):
- **Timing-safe comparison**: `hmac.compare_digest` instead of `!=` in `dependencies.py`
- **WWW-Authenticate header**: Added `'Bearer realm="scene-atlas"'` to all 401 responses
- **Redundant import**: Removed `StarletteRequest` alias from `main.py`
- **Test coverage**: API endpoint test now asserts all 4 security headers
- **Edge case test**: `AUTH_TOKEN=''` documented as disabling auth (not erroring)

### Key files changed so far:
- [`backend/app/main.py`](../backend/app/main.py) — `SecurityHeadersMiddleware` added after CORS middleware
- [`backend/app/config.py`](../backend/app/config.py) — `auth_token: str | None = None` in Settings
- [`backend/app/api/dependencies.py`](../backend/app/api/dependencies.py) — `verify_auth` dependency
- [`backend/scripts/generate_token.py`](../backend/scripts/generate_token.py) — token generator
- [`.env.example`](../.env.example) — auth section documented
- `backend/tests/unit/test_security_headers.py` — 2 tests
- `backend/tests/unit/test_auth_config.py` — 2 tests
- `backend/tests/unit/test_auth_dependency.py` — 6 tests (incl. WWW-Authenticate + empty string)

---

## What Remains To Be Done

Use the master plan at [`/home/joe/.claude/plans/hashed-squishing-cake.md`](/home/joe/.claude/plans/hashed-squishing-cake.md) for detailed step-by-step instructions for each task. Summary below:

### Task 4: Apply auth to all routers (NEXT — do this first)

**File:** `backend/app/main.py` lines 179–187 (the 9 `app.include_router` calls)

1. Add `from fastapi import Depends` to the existing FastAPI import line
2. Add `from .api.dependencies import verify_auth` import
3. Wrap all 9 router includes with `dependencies=[Depends(verify_auth)]`
4. Write integration tests in `backend/tests/integration/test_auth_integration.py` (5 tests — see master plan)
5. Verify existing tests still pass (`auth_token` is `None` in fixtures so no regressions)

**Critical note:** `/health` and `/` root are NOT in the routers so they stay unauthenticated — correct for monitoring probes.

**Also add a startup log** when `auth_token` is set (reviewer suggestion #7 from code review):
```python
# In lifespan, after "Server ready" log:
if settings.auth_token:
    logger.info("Bearer token authentication is enabled")
```

---

### Task 6: Rate limiting with slowapi

**Files:** `pyproject.toml`, `backend/app/main.py`, `backend/app/config.py`, plus 4 router files

Steps:
1. Add `"slowapi>=0.1.9,<1.0"` to `[project]` dependencies in `pyproject.toml`, then `uv sync`
2. Add rate limit config to `backend/app/config.py` (see master plan for exact fields)
3. Create `backend/app/api/rate_limits.py` — shared `Limiter` instance (avoids circular imports)
4. In `backend/app/main.py`: import the limiter, set `app.state.limiter`, add `SlowAPIMiddleware`, add `RateLimitExceeded` handler
5. Apply `@limiter.limit(lambda: settings.rate_limit_X)` to 4 endpoints:
   - `backend/app/api/imports.py` — upload-batch: `rate_limit_upload`
   - `backend/app/api/search.py` — rebuild-embeddings: `rate_limit_expensive`
   - `backend/app/api/export.py` — export library: `rate_limit_expensive`
   - `backend/app/api/system.py` — purge library: `rate_limit_destructive`
6. Each decorated endpoint **must** have a `request: Request` parameter (SlowAPI requires it)
7. Write smoke test in `backend/tests/integration/test_rate_limits.py`

**Watch out for:** The `@limiter.limit()` decorator with a lambda needs SlowAPI ≥0.1.9. If using a string literal directly, note that config values won't be overridable at runtime.

---

### Task 7: CI/CD security scanning

**File:** `.github/workflows/ci.yml`, `pyproject.toml`

1. Add to `pyproject.toml` dev deps: `"pip-audit>=2.7.0,<3.0"` and `"bandit>=1.7.0,<2.0"`
2. Run `uv sync --extra dev` locally, then `uv run pip-audit --desc` and `uv run bandit -r backend/app backend/pipeline -ll` to see baseline
3. Add new `backend-security` job in CI (parallel to `backend-unit`, after `backend-lint`) — see master plan for exact YAML
4. Add `npm audit --audit-level=high` step to `frontend-lint` job
5. All new steps use `continue-on-error: true` to establish baseline without blocking CI

---

### Task 8: CORS startup warning

**File:** `backend/app/main.py`

In the `lifespan` function, after `logger.info("Server ready on ...")`:
```python
_default_cors = {"http://localhost:3000", "http://localhost:5173", "http://localhost:8000"}
if settings.app_mode == "server" and set(settings.cors_origins) == _default_cors:
    logger.warning(
        "CORS origins are still set to localhost defaults but APP_MODE=server. "
        "Set CORS_ORIGINS in your .env to your actual frontend origin."
    )
```

This is low-risk and takes ~5 minutes.

---

### Task 9: Frontend auth via Vite environment variable

**Files:** `frontend/src/vite-env.d.ts`, `frontend/src/lib/api.ts`, `frontend/.env.example`

1. **`vite-env.d.ts`** — Replace file contents (currently just `/// <reference types="vite/client" />`) with the full `ImportMetaEnv` + `ImportMeta` interface declarations including `VITE_AUTH_TOKEN?: string`

2. **`api.ts`** — Extend the existing request interceptor at lines 41–46:
   ```typescript
   api.interceptors.request.use((config) => {
     if (!config.baseURL) {
       config.baseURL = getApiBaseUrl()
     }
     const token = import.meta.env.VITE_AUTH_TOKEN
     if (token) {
       config.headers.set('Authorization', `Bearer ${token}`)
     }
     return config
   })
   ```
   Then add a response interceptor immediately after for 401 logging (see master plan).

3. **`frontend/.env.example`** — Create new file with `VITE_AUTH_TOKEN` documented.

4. Run `cd frontend && npx vitest run` — all existing tests should pass, the new env var addition is additive only.

5. Run `npx eslint src/lib/api.ts src/vite-env.d.ts` and `npx prettier --write src/lib/api.ts src/vite-env.d.ts`

---

## How to Continue

```bash
# Enter the worktree
cd /home/joe/scene-atlas/.worktrees/security-phase-2

# Verify baseline
uv run python -m pytest backend/tests/unit/ -q
# Expected: 427 passed

# Start with Task 4 (apply auth to routers)
# Then 6, 7, 8, 9 in order
```

After all 9 tasks are complete, use **`superpowers:finishing-a-development-branch`** to decide how to merge (PR vs direct merge to main).

---

## Architecture Decisions Made

- **No per-router auth granularity** — all 9 routers get auth. `/health` and `/` stay open (they're not in routers).
- **`not settings.auth_token` guard** — empty string disables auth, same as None. This is documented with a test.
- **`hmac.compare_digest`** — stdlib, no extra dependency, constant-time comparison.
- **Shared `rate_limits.py` module** — avoids circular import between `main.py` and routers.
- **`VITE_AUTH_TOKEN` build-time env var** — baked into JS bundle. Token is visible in bundle source but required to access the API anyway. Acceptable for a personal tool.
- **`continue-on-error: true`** on all CI security scans — establishes baseline without blocking existing CI.
