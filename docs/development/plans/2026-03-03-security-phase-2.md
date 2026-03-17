# Security Hardening — Phase 2 Handover

**Date**: 2026-03-03
**Branch**: work directly on `main` for small fixes, or create a new worktree for larger items
**Reference**: `design/security.md` — full evaluation with all findings

---

## What Was Done in Phase 1

The path traversal vulnerability (Finding #2) was eliminated by redesigning file staging:

- Uploaded files are now stored as flat UUID-named files: `staging/{job_id}/{uuid}.jpg`
- A `.file_map.json` sidecar maps `{relative_path → staging_key}`
- The frontend and group detection logic still use `relative_path` as the logical identifier
- This also eliminates Windows MAX_PATH issues from deep folder structures

**All 670 tests pass.** Key files changed: [backend/app/api/imports.py](backend/app/api/imports.py), [backend/pipeline/ingestion.py](backend/pipeline/ingestion.py), [backend/pipeline/tasks/image_processing.py](backend/pipeline/tasks/image_processing.py), and the integration test suite.

---

## Remaining Findings (in priority order)

### 1. CRITICAL — No Authentication or Authorization

All endpoints are publicly accessible, including destructive operations:
- `DELETE /api/v1/system/library` — purges entire library
- `POST /api/v1/system/tags/reset` — resets all tags
- `POST /api/v1/search/rebuild-embeddings` — expensive ML job
- `GET /api/v1/export/library` — downloads entire library as ZIP

**Implementation approach**:
- Add `AUTH_TOKEN` (str | None) to `backend/app/config.py` (Settings class)
- Create `backend/app/api/auth.py` with a FastAPI dependency:
  - If `AUTH_TOKEN` is unset → skip (backwards compat with Electron/dev)
  - If set → validate `Authorization: Bearer <token>` header; 401 on mismatch
- Apply the dependency to all router includes in `backend/app/main.py`
- Add integration tests: unauthenticated → 401, correct token → 200, wrong token → 401
- Add to `.env.example` and deployment docs

**Key design constraint**: When `AUTH_TOKEN` is not configured, the app must behave exactly as before. This preserves Electron and developer mode compatibility.

You should also consider what approaches there could be for generating this token? Would it be possible to automate key generation and handover between front and backend or do we need to provide the user a covenience function for generating it on first urn?

### 2. HIGH — No Rate Limiting

Any endpoint can be called unlimited times. Particularly dangerous for:
- `/api/v1/imports/*/upload-batch` — disk fill
- `/api/v1/search/rebuild-embeddings` — CPU exhaustion
- `/api/v1/export/library` — bandwidth exhaustion

**Implementation approach**: Add `slowapi` to dependencies. Wrap the FastAPI app with `SlowAPI` middleware in `backend/app/main.py`. Apply `@limiter.limit()` decorators:
- General endpoints: `"60/minute"`
- Upload batch: `"20/minute"`
- Rebuild embeddings + export: `"2/minute"`
- Library purge: `"1/minute"`

Rate limits should be configurable via settings (env vars) so they can be disabled for local/dev mode.

### 3. MEDIUM — No Security Headers

**Location**: `backend/app/main.py` — no security header middleware

Add a middleware that sets on every response:
```python
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=()
```

Note: `Strict-Transport-Security` should come from the reverse proxy, not the app.

### 4. MEDIUM — No Security Scanning in CI/CD

**Location**: `.github/workflows/ci.yml`

Add two steps after dependency installation:
1. `pip-audit` — scans Python deps for known CVEs
2. `npm audit --audit-level=high` — scans JS deps

Consider `bandit -r backend/` for Python SAST. Start with `continue-on-error: true` to establish a baseline, then enforce once clean.

### 5. MEDIUM — Electron IPC Accepts Arbitrary Paths

**Location**: `electron/src/main.ts:126-140`

`fs:read-directory` and `fs:read-file-bytes` accept any path from the renderer process. A compromised renderer could read arbitrary files. Add path validation to ensure requested paths are within allowed directories (user home or configured data directory). Lower priority for hosted mode.

### 6. LOW — CORS + CSP Hardening

**CORS** (`backend/app/main.py:170-176`): `allow_credentials=True` with localhost defaults. Add a startup warning when `app_mode == "server"` and CORS origins are still localhost defaults.

**CSP** (`frontend/index.html`): `connect-src 'self' http://localhost:*` — the `localhost:*` is only needed for Electron/dev. For hosted mode it should be `'self'` only. Electron can inject the localhost variant at build time.

### 7. LOW — CSRF Protection

Currently moot without authentication. Once Finding #1 is implemented, add CSRF protection simultaneously via `SameSite=Strict` cookie attributes or CSRF tokens.

---

## Suggested Sequencing for Phase 2

1. **Security headers** (Finding 3) — 30 min, zero risk, immediate value
2. **Auth middleware** (Finding 1) — 2-3 hours, most important for hosted mode
3. **Rate limiting** (Finding 2) — 1-2 hours, depends on auth being in place first
4. **CI/CD scanning** (Finding 4) — 1 hour, non-breaking, can go in parallel
5. **CORS/CSP** (Finding 6) — 30 min, low risk
6. **Electron IPC** (Finding 5) — lower priority, Electron-specific

---

## Context on the Codebase

- `backend/app/main.py` — app entry point, where middleware and router includes live
- `backend/app/config.py` — `Settings` class (Pydantic, reads env vars)
- `backend/app/api/dependencies.py` — currently only `get_db()`; auth dependency goes here
- `.github/workflows/ci.yml` — CI pipeline
- Tests: `uv run pytest` — always run from repo root
- The app has three modes: `app_mode` in settings (`"electron"`, `"server"`, `"dev"`)
