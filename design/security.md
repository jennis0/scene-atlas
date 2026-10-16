# Security Evaluation — Scene Atlas (Hosted Mode)

**Date**: 2026-03-14 (updated)
**Scope**: Hosted deployment behind reverse proxy

## Deployment Model

Scene Atlas has three deployment modes:
1. **Electron desktop app** — backend runs as local sidecar; OS provides isolation
2. **Web server behind reverse proxy** — proxy handles TLS; this doc evaluates what else is needed
3. **Developer mode** — localhost only, no security expectations

This evaluation focuses on mode 2.

**Server mode deployment requirement**: Until session-based authentication is implemented, server mode MUST be behind network-level access control (VPN, Tailscale, Cloudflare Access, or similar). The application currently has no authentication — all API endpoints are accessible to anyone who can reach the server.

---

## What's Already Done Well

| Area | Details |
|------|---------|
| SQL injection | All queries use SQLAlchemy ORM; FTS5 input sanitized in `fts_service.py` |
| XSS | No unsafe DOM injection patterns; all content via React text interpolation |
| ZIP bombs | `check_zip_safety()` in `validation.py` validates count, size, zip-slip |
| MIME validation | `verify_media_mime()` uses PIL to verify headers match extensions |
| File storage | UUID hash-sharded keys, not user-controlled names (`image_store.py`) |
| Error handling | Global handler returns generic messages; details logged server-side only |
| Secrets | No hardcoded secrets; all config via env vars; `.env` in `.gitignore` |
| Supply chain | Lock files (`uv.lock` with hashes, `package-lock.json`) present |
| CSP | Restrictive Content-Security-Policy meta tag in `index.html` |
| Pre-commit | Husky + lint-staged enforces ruff and eslint |
| Code safety | No shell-invocation or code-execution functions in backend |

---

## Findings

### 1. CRITICAL: No Authentication or Authorization

**Status**: DEFERRED to Phase 3 (session-based auth with multi-user support)

All endpoints are currently public. Network-level isolation is required until session-based auth is implemented. Bearer-token auth was prototyped on `feature/security-phase-2` but abandoned because the token baked into the frontend JS bundle provides no real security against anyone who can access the frontend URL.

**Phase 3 plan**: Login page, server-side sessions (HTTP-only cookies), CSRF protection. This approach solves the `<img src>` authentication problem natively (cookies are sent automatically) and provides a foundation for future multi-user support.

### 2. HIGH: Path Traversal in Upload Endpoint

**Status**: FIXED — staged files use server-generated names (`import_items.staging_key`); `relative_path` never reaches the filesystem

### 3. HIGH: No Rate Limiting

**Status**: DONE (Phase 2)

Rate limiting implemented via `slowapi` with two tiers:
- **expensive** (2/min): `POST /search/rebuild-embeddings`, `GET /export/library`, `PATCH /settings/`, `POST /tags/retag-all`, `POST /tags/packs/{pack_name}/import`, `POST /images/backfill-grids`
- **destructive** (1/min): `DELETE /system/library`, `POST /system/tags/reset`

The `/imports` endpoints are intentionally NOT rate-limited. An import sends one `PUT /imports/{id}/items/{item_id}/content` per file (≈10k requests for a 10k-file import), so a per-IP limit would throttle legitimate imports. They are bounded instead by `max_import_file_size` (413 on the streamed body), `max_import_items` per job, the seal-time free-space check, and the `acquire_heavy_op` semaphore on the CPU-heavy seal and archive-expansion endpoints. The client retries 429/5xx up to 5 times per file, then records a resumable local failure. Reverse proxies with their own rate limits must allow for the per-file request volume.

Configurable via `RATE_LIMIT_EXPENSIVE`, `RATE_LIMIT_DESTRUCTIVE` env vars. Disable entirely with `RATE_LIMIT_ENABLED=false`.

**Reverse proxy requirement**: The proxy MUST overwrite (not append to) `X-Forwarded-For` so rate limiting keys on the real client IP. If the proxy appends, an attacker can spoof the header to get unlimited fresh rate limit buckets.

### 4. MEDIUM: No Security Headers

**Status**: DONE (Phase 2)

Pure ASGI `SecurityHeadersMiddleware` adds to every response:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=()`

HSTS intentionally omitted — must come from the reverse proxy to avoid breaking non-TLS deployments (Electron, local dev).

### 5. MEDIUM: No Security Scanning in CI/CD

**Status**: DONE (Phase 2)

CI now includes:
- `pip-audit --desc` (Python CVE scanning)
- `bandit -r backend/app backend/pipeline -ll` (Python SAST)
- `npm audit --audit-level=high` (Frontend dependency audit)

All use `continue-on-error: true` initially. Tracked in `technical-debt.md` to remove within 2 weeks once baseline is triaged.

### 6. MEDIUM: Electron IPC Accepts Arbitrary Paths

**Status**: Not yet implemented (future work)

### 7. MEDIUM: CORS Configuration

**Status**: DONE (Phase 2)

Startup warning logged when `APP_MODE=server` and CORS origins are still set to localhost defaults.

### 8. LOW: CSP connect-src Too Broad

**Status**: Not yet implemented (future work)

### 9. LOW: No CSRF Protection

**Status**: Will be implemented alongside session-based auth (Phase 3)

### 10. LOW: No Dependency Vulnerability Scanning

**Status**: DONE — covered by Finding 5

---

## Staging Security Redesign

The path traversal issue (finding 2) was resolved by staging uploads under server-generated filenames instead of user-supplied relative paths.

**Before**: `staging_dir / "Author/GroupName/map.jpg"` (user-controlled path)
**After**: `staging_dir / {job_id} / {staging_key}` (server-generated, safe by construction)

`import_items.relative_path` is kept only for display, grouping and resume matching, and `item_id` is always scoped to its `job_id`. See [ingestion.md §7](ingestion.md#7-upload-protocol).

---

## Remediation Priority

1. ~~Path traversal fix via hash-based staging~~ (DONE)
2. ~~Security headers~~ (DONE — Phase 2)
3. ~~Rate limiting~~ (DONE — Phase 2)
4. ~~CI/CD security scanning~~ (DONE — Phase 2)
5. ~~CORS startup warning~~ (DONE — Phase 2)
6. Session-based authentication (Phase 3 — planned)
7. Electron IPC validation (future)
8. CORS/CSP hardening (future)
