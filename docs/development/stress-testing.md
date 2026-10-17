# Stress Testing the Import Pipeline

The stress testing suite exercises the Scene Atlas import pipeline under concurrent load, adversarial input, and failure conditions.  It runs against a **real server** (not mocked), testing the actual SQLite WAL mode contention, LanceDB write serialisation, and the ThreadPoolExecutor job runner.

::: warning Out of date
The import scenarios in `stress_tests/scenarios.py` still drive the import API that ADR-018 removed (`/imports/init`, `/upload-batch`, `/analyse`, `/confirm-all`, `/check-hashes`) and check for removed behaviour (`mark_interrupted_jobs`, `expire_stale_jobs`, `broken`/`expired` job states). They will fail against the current backend until they are ported to the manifest → seal → per-file `PUT` flow and the `active`/`paused`/`completed`/`cancelled` job states. The descriptions below document the scenarios as written. The [library-scale benchmark](#library-scale-read-benchmark) does not use the import API.
:::

## Quick start

```bash
# From the repository root
uv run python -m stress_tests list                          # show all scenarios
uv run python -m stress_tests generate-fixtures             # pre-generate test files (~45 MB)
uv run python -m stress_tests run --scenario endpoint_spam  # single fast scenario
uv run python -m stress_tests run --all --quick             # all scenarios, reduced load (~7 min)
uv run python -m stress_tests run --all                     # full suite (~25–40 min)
```

## Requirements

- **Python / uv** — already a project dependency; run via `uv run python -m stress_tests …`
- **Pillow** — already a dev dependency (image fixture generation)
- **ffmpeg** — *optional*; only needed for video fixtures (MP4/WebM).  All non-video scenarios work without it.  Install from [ffmpeg.org](https://ffmpeg.org/) and add to `PATH`.

## Flags

| Flag | Effect |
|------|--------|
| `--quick` | Reduces concurrency and file counts.  Full suite runs in ~7 min instead of ~40 min. |
| `--large` | Enables 500 MB+ fixture variants and 60 s video files.  Requires ~7 GB free disk. |

## Architecture

Each scenario:
1. Gets a **fresh server process** (uvicorn subprocess, isolated temp data directory)
2. Waits for `SCENE_ATLAS_READY` on stdout, then warms the CLIP model
3. Runs its scenario logic via `httpx.AsyncClient` + `asyncio`
4. On failure: saves `server.log` + `db.sqlite` to `stress_tests/results/<timestamp>_<name>/`
5. The server is stopped and the next scenario starts clean

No new Python dependencies are required — `httpx` and `Pillow` are already dev deps.

## Scenarios

### 1. `concurrent_imports` — concurrent full import flows

Runs 100 coroutines (quick: 10) each doing a complete import: init → upload → analyse → confirm-all → poll.

**What it catches:** SQLite WAL contention, LanceDB write serialisation bottleneck, ThreadPoolExecutor starvation, zombie jobs.

**Pass criteria:** All jobs reach a terminal state (`completed`, `failed`, or `cancelled`), zero HTTP 5xx responses.

---

### 2. `endpoint_spam` — race condition flooding

Fires many concurrent requests against the same job to find race conditions:

1. 100 concurrent cancels → exactly one returns 200, rest return 409/404
2. 100 concurrent status polls → all 200, consistent status value
3. 100 concurrent uploads to a cancelled job → all 409
4. 100 concurrent confirm-all calls to a staging job → at most one succeeds

**What it catches:** Non-atomic state transitions, duplicate group processing.

**Pass criteria:** No 5xx responses, state transitions atomic.

---

### 3. `cancellation_chaos` — cancel at every pipeline stage

Starts four imports and cancels each at a different stage:

- (a) During upload, before analyse
- (b) In staging state, after analyse but before confirm
- (c) In active state, immediately after confirm-all (may still be processing)
- (d) After completion → expects 409

**What it catches:** Orphaned staging directories, jobs stuck in non-terminal states.

**Pass criteria:** Correct HTTP codes, all jobs reach terminal state.

---

### 4. `malformed_input` — corrupted file handling

Uploads each malformed fixture (JPEG, PNG, WebP, MP4, WebM, ZIP) and a near-zip-bomb.  Each file has a valid magic-byte header but corrupted body.

**Expected behaviour:**
- Malformed images/videos: server skips the file (200 with `skipped_invalid` list)
- Near-zip-bomb: server returns 413 (rejected by `check_zip_safety()` before extraction)

**What it catches:** PIL/ffmpeg hangs on corrupt data, server crashes, memory exhaustion.

**Pass criteria:** No 5xx responses, all requests complete within 30 s.

---

### 5. `large_uploads` — big files, sequential then concurrent

Uploads large video and ZIP files.  Skipped in `--quick` mode.  Use `--large` to test 500 MB+ variants.

Runs two sub-tests:
- Sequential upload of each large file
- 5 concurrent uploads of the same large file

**What it catches:** OOM from concurrent streaming, partial state left behind after 413.

**Pass criteria:** All requests complete or reject cleanly (no 5xx, no timeout).

---

### 6. `concurrent_move_groups` — simultaneous group mutations

Imports images into two groups, then fires 20 concurrent `move-images` requests targeting the same image IDs.

**What it catches:** Race conditions in the group-assignment logic.

**Pass criteria:** Exactly one move succeeds (200), the rest return 400/404.  No duplicate assignments.

---

### 7. `duplicate_hash_race` — content-hash dedup under concurrency

Uploads the **same image bytes** to 50 concurrent import jobs.  The pipeline's `/check-hashes` dedup should handle this without creating duplicate `Image` rows in the database.

**What it catches:** Race conditions in hash-based deduplication.

**Pass criteria:** All jobs complete, no 5xx responses.

---

### 8. `server_restart_recovery` — crash recovery

Starts 3 imports, leaves them in `active` state, force-kills the server, restarts it, then checks that `mark_interrupted_jobs()` transitioned all in-flight jobs to `broken`.

**What it catches:** Jobs stuck in `uploading`/`staging`/`active` after a crash.

**Pass criteria:** All jobs are in a terminal state after restart.

---

### 9. `large_batch_imports` — sustained heavy load

Runs 10 jobs (quick: 2) each uploading 1 000 files (quick: 100) in batches of 50.

**What it catches:** Memory growth under sustained load, CLIP throughput, per-file error isolation.

**Pass criteria:** All jobs reach terminal state, no 5xx responses.

---

### 10. `scheduler_interference` — maintenance tasks under load

Runs 20 concurrent imports (quick: 5) while the scheduler's periodic tasks (`cleanup_staging`, `expire_stale_jobs`) are running in the background.

**What it catches:** Scheduler prematurely cleaning up staging directories for in-progress jobs, false expiry of slow imports.

**Pass criteria:** No jobs expired (`status == "expired"`), all reach terminal state.

---

## Failure artifacts

When a scenario fails, artifacts are saved to:

```
stress_tests/results/<timestamp>_<scenario-name>/
├── server.log      # Full DEBUG-level backend log
├── db.sqlite       # DB snapshot at the end of the run
└── summary.json    # Pass/fail, timing, error details (machine-readable)
```

These directories are gitignored.

## Fixtures

Fixtures are generated into `stress_tests/.fixtures/` (gitignored) on first use.

| Fixture | Description | Default size |
|---------|-------------|--------------|
| `sample.jpg/png/webp` | Single valid images for basic tests | ~50–200 KB |
| `small.zip` | ZIP of 10 images | ~3 MB |
| `large_100.zip` | ZIP of 100 images | ~25 MB |
| `near_bomb.zip` | 800 entries × 3 MB zeros (DEFLATE) — compressed to ~1.6 MB, uncompressed metadata = 2.4 GB | ~1.6 MB |
| `malformed_5mb.jpg/png/webp/mp4/webm/zip` | Valid magic bytes + corrupt body | 5 MB each |
| `video_720p_1s.mp4/webm` | ffmpeg color bars | ~500 KB |

With `--large`: malformed files grow to 500 MB each, videos become 60 s 1080p, ZIP grows to 1 000 images.

Fixtures are cached: if the file already exists it won't be regenerated.  Delete `stress_tests/.fixtures/` to force regeneration.

## Library-scale read benchmark

`stress_tests/library_scale.py` builds a synthetic SQLite library of N images directly (no HTTP, no models; groups of ~7, 4 tags and 5 colours per image, migrated to the current schema) and reports SQL query counts and wall time for the search, gallery, group, and tag read paths. Semantic search is replaced by a fake.

```bash
uv run python -m stress_tests.library_scale build 56000 --db /tmp/lib.db
uv run python -m stress_tests.library_scale run --db /tmp/lib.db
```

Use it to check a change for N+1 queries or slow aggregates at real-library scale. Never point `--db` at a real library database: `build` deletes the file first.
