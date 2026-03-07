# Security Evaluation — Scene Atlas (Hosted Mode)

**Date**: 2026-03-03
**Scope**: Hosted deployment behind reverse proxy

## Deployment Model

Scene Atlas has three deployment modes:
1. **Electron desktop app** — backend runs as local sidecar; OS provides isolation
2. **Web server behind reverse proxy** — proxy handles TLS; this doc evaluates what else is needed
3. **Developer mode** — localhost only, no security expectations

This evaluation focuses on mode 2.

---

## What's Already Done Well

| Area | Details |
|------|---------|
| SQL injection | All queries use SQLAlchemy ORM; FTS5 input sanitized in `fts_service.py:14-27` |
| XSS | No unsafe DOM injection patterns; all content via React text interpolation |
| ZIP bombs | `check_zip_safety()` in `validation.py:29-68` validates count, size, zip-slip |
| MIME validation | `verify_media_mime()` uses PIL to verify headers match extensions |
| File storage | UUID hash-sharded keys, not user-controlled names (`image_store.py:82-92`) |
| Error handling | Global handler returns generic messages; details logged server-side only |
| Secrets | No hardcoded secrets; all config via env vars; `.env` in `.gitignore` |
| Supply chain | Lock files (`uv.lock` with hashes, `package-lock.json`) present |
| CSP | Restrictive Content-Security-Policy meta tag in `index.html` |
| Pre-commit | Husky + lint-staged enforces ruff and eslint |
| Code safety | No shell-invocation or code-execution functions in backend |

---

## Findings

### 1. CRITICAL: No Authentication or Authorization

**Location**: `backend/app/api/dependencies.py`

All endpoints are public, including destructive ones:

| Endpoint | Risk |
|----------|------|
| `DELETE /api/v1/system/library` | Purges entire library |
| `POST /api/v1/system/tags/reset` | Resets all tags |
| `DELETE /api/v1/images/{id}` | Deletes images |
| `POST /api/v1/search/rebuild-embeddings` | CPU-intensive ML job |
| `GET /api/v1/export/library` | Downloads entire library |
| `POST /api/v1/imports/*` | Upload arbitrary files |

**Remediation**: Add optional bearer token auth middleware. Skip when `AUTH_TOKEN` is unset (Electron/dev). Apply to all mutating endpoints.

### 2. HIGH: Path Traversal in Upload Endpoint

**Location**: `backend/app/api/imports.py:273`

User-supplied `relative_path` was used directly to construct disk paths without `is_path_within()` validation. The preview endpoint had this check but the upload path did not.

**Status**: FIXED — staging now uses UUID-based flat filenames (see below).

### 3. HIGH: No Rate Limiting

**Impact**: Unlimited calls to upload, rebuild-embeddings, export, and library purge endpoints.

**Remediation**: Add `slowapi` middleware with tiered limits:
- General: 60 req/min
- Upload: 10 req/min
- Expensive ops: 2 req/min
- Destructive: 1 req/hour

### 4. MEDIUM: No Security Headers

**Location**: `backend/app/main.py`

Missing: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.

**Remediation**: Add response header middleware. Note: `Strict-Transport-Security` should come from the reverse proxy.

### 5. MEDIUM: No Security Scanning in CI/CD

**Location**: `.github/workflows/ci.yml`

**Remediation**: Add `pip-audit` and `npm audit --audit-level=high` steps. Consider `bandit` for Python SAST.

### 6. MEDIUM: Electron IPC Accepts Arbitrary Paths

**Location**: `electron/src/main.ts:126-140`

`fs:read-directory` and `fs:read-file-bytes` accept any path from the renderer. Should validate paths are within allowed directories.

### 7. MEDIUM: CORS Configuration

**Location**: `backend/app/main.py:170-176`

`allow_credentials=True` with localhost defaults. Needs explicit configuration for hosted deployment.

**Remediation**: Add startup warning when server mode uses localhost CORS origins.

### 8. LOW: CSP connect-src Too Broad

`connect-src 'self' http://localhost:*` should be `'self'` only for hosted mode. Electron can inject localhost variant at runtime.

### 9. LOW: No CSRF Protection

Moot without authentication. Should be added alongside auth (finding 1).

### 10. LOW: No Dependency Vulnerability Scanning

Lock files exist but no automated scanning. Covered by finding 5.

---

## Staging Security Redesign

The path traversal issue (finding 2) was resolved by redesigning the staging directory to use UUID-based flat filenames instead of user-supplied relative paths.

**Before**: `staging_dir / "Author/GroupName/map.jpg"` (user-controlled path)
**After**: `staging_dir / "a1b2c3d4.jpg"` (UUID, safe by construction)

A `.file_map.json` sidecar maps `{relative_path: staging_key}` so group detection and the frontend still use original paths as logical identifiers.

This also eliminates Windows MAX_PATH issues from deeply nested folder uploads.

---

## Implementation Status

- **Finding #2 (path traversal):** FIXED via staging redesign (UUID-flat-file structure with `.file_map.json` sidecar)
- **Findings 1, 3–10:** Remain unimplemented in the main branch
- **Security Phase 2:** Implementation exists on an unpushed `feature/security-phase-2` branch covering auth, rate limiting, security headers, and CI scanning

## Remediation Priority

1. Path traversal fix via hash-based staging (done)
2. Authentication middleware (on feature/security-phase-2 branch, not merged)
3. Rate limiting (on feature/security-phase-2 branch, not merged)
4. Security headers (on feature/security-phase-2 branch, not merged)
5. CI/CD security scanning (on feature/security-phase-2 branch, not merged)
6. Electron IPC validation (future)
7. CORS/CSP hardening (future)
