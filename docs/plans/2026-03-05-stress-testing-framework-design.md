# Stress Testing Framework for Import Pipeline

## Context

The Scene Atlas import pipeline handles concurrent file uploads, batch processing (CLIP embeddings, thumbnails, grid detection), cancellations, and error recovery — backed by SQLite WAL mode, embedded Qdrant with a single RLock, and an in-process ThreadPoolExecutor (2 workers). Before releases, developers need confidence that the pipeline handles abuse gracefully.

No stress testing infrastructure exists today. This plan builds a lightweight, easy-to-run suite that developers execute locally before releases. The focus is on surfacing crashes, stuck jobs, data corruption, resource leaks, and race conditions — not just clean imports, but also graceful failure.

## Parallel Change Constraint

**`docs/plans/2026-03-05-remove-import-confirmation.md`** is removing the confirmation/review layer in parallel. The following must NOT be used anywhere in stress tests:

| Removed item | Replacement |
|---|---|
| `/confirm` (single-group endpoint) | Use `/confirm-all` only |
| `/finalize` endpoint | Removed — no replacement needed |
| `/groups/confirm-review` endpoint | Removed — no replacement needed |
| `awaiting_input` job status | Only valid terminal states: `completed`, `failed`, `cancelled` |
| `pending_groups`, `all_confirmed` fields | Do not read or assert on these |
| `needs_review` image field | Do not read or assert on this |

Specifically affected scenarios:
- **`endpoint_spam`** — concurrent confirm sub-test: use `/confirm-all`, never `/confirm`
- **`cancellation_chaos`** — do not test cancellation from `awaiting_input`; only test: during upload, during analysis, during processing, after `completed`/`failed`
- **`scheduler_interference`** — `expire_stale_jobs` will no longer target `awaiting_input`; verify it doesn't expire legitimately slow active jobs

## Architecture Decisions

- **No Locust** — import flows are multi-step stateful workflows (init→upload→analyse→confirm→poll). Locust is designed for simple HTTP load patterns and adds conceptual overhead + a dependency for features we can achieve with `asyncio.gather()` + `httpx.AsyncClient` + a 50-line timing layer.
- **httpx + asyncio** — already a dev dependency, zero new deps, native async concurrency, easy to write sequential multi-step flows with concurrent execution.
- **Real server subprocess** — uvicorn in subprocess with isolated test DB + storage. Real thread pool, event loop, SQLite WAL contention, Qdrant RLock contention.
- **Terminal-first results** — `PASS`/`FAIL` printed to stdout immediately. Detailed artifacts (server log, DB snapshot) saved only on failure.
- **Server restart between scenarios** — each scenario gets a clean baseline. No polluted state from previous runs.
- **Small fixtures by default** — 5MB malformed files test the same code paths as 500MB. A `--large` flag enables 500MB+ fixtures for disk I/O stress testing.

## Package Structure

```
stress_tests/
├── __init__.py
├── __main__.py          # entry: python -m stress_tests
├── run.py               # CLI (argparse), server lifecycle, results collection
├── fixtures.py          # synthetic file generation (images, videos, zips, malformed)
├── scenarios.py         # all scenarios as async functions, parameterised
├── .fixtures/           # gitignored, generated test files
└── results/             # gitignored, failure artifacts only
```

~500 lines of Python total. If scenarios grow complex enough to split, split then.

## CLI Interface

```bash
python -m stress_tests run --all                           # all scenarios, headless
python -m stress_tests run --scenario concurrent-imports   # single scenario
python -m stress_tests run --all --quick                   # reduced load, <5 min total
python -m stress_tests run --all --large                   # enable 500MB+ fixture variants
python -m stress_tests generate-fixtures                   # pre-generate only
python -m stress_tests list                                # show scenarios + estimated runtime
```

## Server Lifecycle (`run.py`)

1. **Pre-flight checks**: disk space (warn if <10GB free), ffmpeg availability (warn if absent, skip video fixtures)
2. Create temp directory for test DB + image store + staging + logs
3. Start uvicorn subprocess with env var overrides: `DATABASE_URL`, `STORE_IMAGES_DIR`, `STORE_THUMBNAILS_DIR`, `STAGING_DIR`, `LOG_LEVEL=DEBUG`
4. Use **port 0** (OS-assigned) — capture actual port from server stdout to avoid conflicts
5. **Health + CLIP ready gate**: poll `/health` until healthy, then poll a status endpoint or wait a configurable warm-up period until CLIP model is loaded (avoids thundering-herd on first requests)
6. Run scenario
7. On failure: copy server log + DB snapshot to `results/<timestamp>_<scenario>/`
8. **Shutdown (cross-platform)**:
   - Unix: `SIGTERM` → wait 10s → `SIGKILL`
   - Windows: `subprocess.terminate()` → wait 10s → `taskkill /F /T /PID <pid>` (kills process tree, including any uvicorn child workers)
9. **Fresh server per scenario** in `--all` mode — restart between each for clean baselines

### WAL Mode Note
The test DB is created by the server's own `init_db()` which sets WAL mode. No special handling needed, but this is a known dependency — if `init_db()` changes, stress test DB behaviour changes too.

## Fixture Generation (`fixtures.py`)

### Hash Uniqueness Strategy
- **Loose images**: PIL random-noise with **deterministic seeds** (per-job seed = base_seed + job_index). Each image is unique, but runs are reproducible.
- **ZIPs of images**: Pack random-noise JPEGs (pre-compressed, realistic ZIP ratio)
- **ZIP bomb test**: Highly-compressible identical PNGs (tests `check_zip_safety()`)
- **Large/malformed files**: Generated once, shared across scenarios

### Fixture Catalog

**Image formats** (PIL, random noise, deterministic seed):

| Fixture | Method | Size |
|---------|--------|------|
| Batch JPEGs | Random RGB noise, varied dimensions (1K–8K px), quality 70-95 | 50KB–2MB each |
| Batch PNGs | RGBA random noise, varied dimensions | 100KB–5MB each |
| Batch WebPs | Random noise, lossy mode, varied quality | 50KB–3MB each |

**Video formats** (ffmpeg, optional — all video scenarios skip gracefully if absent):

| Fixture | Method | Default | `--large` |
|---------|--------|---------|-----------|
| MP4 | ffmpeg: color bars, H.264 | 1s 720p (~500KB) | 60s 1080p (~500MB) |
| WebM | ffmpeg: color bars, VP9 | 1s 720p (~500KB) | 60s 1080p (~500MB) |

**ZIP fixtures**:

| Fixture | Method | Default | `--large` |
|---------|--------|---------|-----------|
| Small ZIP | 10 mixed JPEG/PNG/WebP | ~5MB | ~5MB |
| Large ZIP | 100 mixed images | ~50MB | 1000 images (~500MB–1GB) |
| Near-zip-bomb | Identical compressible PNGs | Small compressed, huge uncompressed | same |

**Malformed fixtures** (valid magic bytes/headers, corrupted body):

| Fixture | Formats | Default | `--large` |
|---------|---------|---------|-----------|
| Malformed image | JPEG, PNG, WebP (valid header + garbage body) | 5MB each | 500MB each |
| Malformed video | MP4, WebM (valid container header + corrupted data) | 5MB each | 500MB each |
| Malformed ZIP | Valid local file header + corrupted entries | 5MB | 500MB |

**Default disk budget**: ~200MB. With `--large`: ~5-7GB.

**Caching**: Simple "if file exists, skip" — no manifest system.

## Scenarios

Each scenario is an `async def` that receives an `httpx.AsyncClient`, base URL, and fixture paths. Returns a `ScenarioResult` dataclass with pass/fail, message, timing stats, and optional failure details.

### 1. `concurrent_imports` — parametric concurrent import jobs
- **Parameters**: `jobs=100, files_per_job=5` (quick mode: `jobs=10, files_per_job=3`)
- **Flow**: Each coroutine runs full import flow (init → upload mix of JPEG/PNG/WebP → analyse → confirm-all → poll until terminal)
- **Pass**: All jobs reach terminal state. Zero 500 errors. No zombie jobs (stuck in non-terminal state).
- **Watch for**: SQLite WAL contention, Qdrant RLock bottleneck, response time degradation

### 2. `large_batch_imports` — few jobs, many files
- **Parameters**: `jobs=10, files_per_job=1000, batch_size=50` (quick: `jobs=2, files_per_job=100`)
- **Flow**: Each coroutine uploads in batches of 50, analyses, confirms
- **Pass**: All jobs complete. Per-file errors classified correctly for any failures.
- **Watch for**: OOM, monotonic memory growth, batch failure isolation, CLIP throughput

### 3. `endpoint_spam` — redundant request flooding + race conditions
- **Sub-tests** (run sequentially within scenario):
  - 100 concurrent cancellations for the same job → first succeeds, rest 409/404, no 500s
  - 100 concurrent status polls for the same job → consistent data, no 500s
  - 100 concurrent upload-batch to a completed job → all 409, no 500s
  - 100 concurrent confirm requests for the same group → exactly one succeeds (race condition test)
- **Pass**: No 500 errors. State transitions are consistent. No duplicate image creation from concurrent confirms.
- **Watch for**: Race conditions in state machine, inconsistent DB reads

### 4. `cancellation_chaos` — cancel at every pipeline stage
- **Flow**: Start multiple imports in parallel. For each, cancel at a different stage:
  - During upload (before analyse)
  - During analysis
  - During processing (after confirm, while batches running)
  - After completion (should be no-op or 409)
- **Pass**: Appropriate status codes. All jobs reach terminal state. Staging directories cleaned up. No orphaned files.
- **Watch for**: Orphaned staging dirs, stuck jobs, incorrect terminal states

### 5. `malformed_input` — corrupted files + zip bomb
- **Flow**: Upload each malformed fixture (JPEG, PNG, WebP, MP4, WebM, ZIP) one at a time. Also upload near-zip-bomb fixture.
- **Pass**: Server rejects or skips each with error classification. No crashes, no hangs (timeout per file: 30s). Zip bomb rejected by `check_zip_safety()` before extraction.
- **Watch for**: PIL/zipfile/ffmpeg hanging on corrupt data, excessive memory during decode

### 6. `large_uploads` — big files, single and concurrent
- **Sub-tests**:
  - Upload large MP4, WebM, ZIP one at a time → accepts or rejects cleanly (413 if over limit)
  - 5 concurrent large file uploads → no OOM, all complete or reject cleanly
- **Pass**: No timeouts. No partial state left behind. Memory stays bounded during streaming.
- **Watch for**: Memory from concurrent streams, disk I/O saturation, staging cleanup

### 7. `concurrent_move_groups` — simultaneous group mutations
- **Flow**: Import images into groups, then fire 20 concurrent move-group requests targeting the same images
- **Pass**: Exactly one move succeeds per image. No duplicate group assignments. No 500s.
- **Watch for**: Race conditions in group assignment

### 8. `duplicate_hash_race` — content-hash dedup under concurrency
- **Flow**: Upload the same file 50 times concurrently across different import jobs
- **Pass**: All jobs complete. Dedup logic produces correct results (no duplicate Image rows with same content_hash). No 500s.
- **Watch for**: Race conditions in hash-based dedup, duplicate DB entries

### 9. `server_restart_recovery` — crash recovery
- **Flow**: Start 5 imports, kill server mid-processing (force kill, no graceful shutdown), restart server
- **Pass**: `mark_interrupted_jobs()` transitions all in-flight jobs to "broken". No stuck jobs in "active"/"uploading" after restart. Server healthy after restart.
- **Watch for**: Jobs stuck in non-terminal state, staging not cleaned up, DB corruption

### 10. `scheduler_interference` — maintenance tasks under load
- **Flow**: Run `concurrent_imports` (reduced: 20 jobs) while ensuring the scheduler's periodic tasks (cleanup_staging, expire_stale_jobs) are active
- **Pass**: Scheduler tasks don't interfere with active imports. No staging dirs deleted for in-progress jobs. No active jobs expired.
- **Watch for**: Race between cleanup_staging and active upload, false expiry of slow jobs

### Estimated Run Times

| Scenario | Default | Quick |
|----------|---------|-------|
| concurrent_imports | ~3-5 min | ~30s |
| large_batch_imports | ~10-20 min | ~2 min |
| endpoint_spam | ~30s | ~15s |
| cancellation_chaos | ~2 min | ~1 min |
| malformed_input | ~30s | ~15s |
| large_uploads | ~2-5 min | skip |
| concurrent_move_groups | ~1 min | ~30s |
| duplicate_hash_race | ~1 min | ~30s |
| server_restart_recovery | ~1 min | ~30s |
| scheduler_interference | ~3 min | ~1 min |
| **Total** | **~25-40 min** | **~7 min** |

## Results & Output

### Terminal Output (primary interface)

```
stress_tests v1.0 — Scene Atlas import pipeline stress testing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASS  concurrent_imports     (47s)  100/100 jobs completed, p95=1.2s, 0 errors
PASS  endpoint_spam          (12s)  400 requests, 0 unexpected errors
FAIL  cancellation_chaos     (38s)  2 jobs stuck in 'active' after cancel
      → Server log: results/2026-03-05T14-30-00_cancellation-chaos/server.log
      → DB snapshot: results/2026-03-05T14-30-00_cancellation-chaos/db.sqlite
PASS  malformed_input        (8s)   6/6 files rejected cleanly
...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Results: 9/10 passed, 1 failed
Failure artifacts saved to: stress_tests/results/2026-03-05T14-30-00_cancellation-chaos/
```

### Failure Artifacts (saved only on failure)

```
stress_tests/results/<timestamp>_<scenario>/
├── server.log              # Full DEBUG-level backend log
├── db.sqlite               # Post-run DB copy for state inspection
└── summary.json            # Machine-readable: pass/fail, timing, error details
```

### Monitoring from Server Logs
Rather than adding test middleware to the application, we parse the server's existing DEBUG logs post-run for:
- Thread count from heartbeat logs (detect thread leaks: start vs end count)
- SQLite busy/WAL warnings
- Qdrant RLock contention (if logged)
- Memory RSS from heartbeat (detect monotonic growth)

## Dependencies

- **httpx** — already a dev dependency
- **PIL** — already available
- **ffmpeg** — system dependency, optional (video fixtures only, all non-video scenarios work without it)
- **No new Python dependencies required**

## Implementation Steps

### Step 1: Package scaffold + CLI + server lifecycle
- Create `stress_tests/` with `__init__.py`, `__main__.py`, `run.py`
- `run.py`: argparse CLI (run/list/generate-fixtures), server subprocess management
- Cross-platform shutdown (Unix signals vs Windows taskkill)
- Health polling + CLIP-ready gate
- Port 0 auto-assignment
- Disk space pre-flight check
- Add `.fixtures/` and `results/` to `.gitignore`
- **Verify**: `python -m stress_tests list` works, server starts and stops cleanly on Windows

### Step 2: Fixture generation
- `fixtures.py`: all generation functions with deterministic seeds
- Image generation (JPEG/PNG/WebP via PIL with random noise)
- Video generation (MP4/WebM via ffmpeg, optional with clear skip warning)
- ZIP packing (small, large, near-zip-bomb)
- Malformed file generation (valid headers + garbage, all 6 formats)
- `--large` flag support for 500MB+ variants
- Simple "if exists, skip" caching
- **Verify**: generated files are correct format/size, unique hashes, malformed files pass magic byte checks but fail decode

### Step 3: Shared helpers + timing layer
- `ScenarioResult` dataclass (pass/fail, message, timing dict, optional failure details)
- `ImportFlow` async class: init → upload → analyse → confirm → poll
- `generate_unique_images(count, seed)` — deterministic per-job image sets
- Timing wrapper collecting request-level stats (count, errors, p50/p95/p99)
- Terminal output formatting (PASS/FAIL with colours if terminal supports it)
- **Verify**: `ImportFlow` completes a full import against a running server

### Step 4: Implement scenarios (priority order)
1. `concurrent_imports` — foundational, validates the whole framework works
2. `endpoint_spam` — race condition detection, fast to run
3. `cancellation_chaos` — lifecycle integrity
4. `malformed_input` — input validation
5. `large_uploads` — resource limits
6. `concurrent_move_groups` — group operation integrity
7. `duplicate_hash_race` — dedup correctness
8. `server_restart_recovery` — crash recovery
9. `large_batch_imports` — sustained heavy load (longest running)
10. `scheduler_interference` — maintenance task interaction

### Step 5: Results collection + `--all` orchestration
- Fresh server per scenario in `--all` mode
- Failure artifact collection (server log + DB snapshot)
- `summary.json` generation
- Terminal summary table
- `--quick` mode with reduced parameters

### Step 6: Documentation + verification
- Docstrings on each scenario explaining what it tests and what failure looks like
- `python -m stress_tests --help` is self-documenting
- End-to-end verification on Windows

## Key Files Referenced

- `backend/app/main.py` — server startup, CLIP background load (line 74), heartbeat (line 128), SIGUSR1 platform guard (line 150), health endpoint
- `backend/app/api/imports.py` — all import endpoints, confirm flow (race condition concern)
- `backend/pipeline/ingestion.py` — batch pipeline, CLIP embedding, error classification
- `backend/app/services/qdrant_service.py` — embedded Qdrant with RLock
- `backend/app/services/job_runner.py` — ThreadPoolExecutor, job lifecycle
- `backend/pipeline/maintenance.py` — `mark_interrupted_jobs()`, `cleanup_stale_staging()`, `expire_stale_jobs()`
- `backend/app/models/database.py` — ImportJob, ImportGroupJob models
- `backend/tests/conftest.py` — existing test patterns (test_client fixture, mock_heavy_services)

## Verification

1. `python -m stress_tests list` — shows all 10 scenarios with estimated runtime
2. `python -m stress_tests generate-fixtures` — generates fixtures, reports sizes
3. `python -m stress_tests run --scenario concurrent-imports --quick` — completes in <30s, prints PASS/FAIL
4. `python -m stress_tests run --all --quick` — all scenarios in <7 min, fresh server per scenario
5. `python -m stress_tests run --all` — full run, ~25-40 min
6. Intentionally break something (e.g., remove cancellation endpoint) and verify the relevant scenario reports FAIL with useful artifacts
7. Run on Windows to verify subprocess management and path handling
