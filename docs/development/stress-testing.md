# Stress Testing the Import Pipeline

The stress testing suite exercises the Scene Atlas import pipeline under concurrent load, adversarial input, and failure conditions.  It runs against a **real server** (not mocked), testing the actual SQLite WAL mode contention, LanceDB write serialisation, and the ThreadPoolExecutor job runner.

The scenarios drive the imports API described in [design/ingestion.md](../../design/ingestion.md#upload-protocol): create job → manifest → (archive upload) → seal → (client hashes) → per-file `PUT`, then poll `GET /imports/{id}` until the job is `completed` or `cancelled`. Jobs never fail; outcomes are item counts (`done`, `duplicate`, `failed`, `skipped`).

## Quick start

```bash
# From the repository root
uv run python -m stress_tests list                          # show all scenarios
uv run python -m stress_tests generate-fixtures             # pre-generate test files (~45 MB)
uv run python -m stress_tests run --scenario endpoint_spam  # single fast scenario
uv run python -m stress_tests run --all --quick             # all scenarios, reduced load (~6 min)
uv run python -m stress_tests run --all                     # full suite (~20–35 min)
```

## Requirements

- **Python / uv** — already a project dependency; run via `uv run python -m stress_tests …`
- **Pillow** — already a dev dependency (image fixture generation)
- **The ONNX model** — every scenario processes images. Each server's isolated data directory links `models/` to `data/models/` (where `uv run python scripts/models/setup_models.py` puts it); set `STRESS_MODELS_DIR` to use another models directory.
- **ffmpeg** — *optional*; only needed for video fixtures (MP4/WebM).  All non-video scenarios work without it.  Install from [ffmpeg.org](https://ffmpeg.org/) and add to `PATH`.

## Flags

| Flag | Effect |
|------|--------|
| `--quick` | Reduces concurrency and file counts.  Full suite runs in ~6 min instead of ~35 min. |
| `--large` | Enables 500 MB+ fixture variants and 60 s video files.  Requires ~7 GB free disk. |

## Architecture

Each scenario:
1. Gets a **fresh server process** (uvicorn subprocess) with its own `APP_DATA_DIR` and `IMAGE_LIBRARY_DIR` under `stress_tests/results/_work_<timestamp>/<scenario>/`, so a run never touches `./data` or `./images`. The work directory is deleted when every scenario passes
2. Waits for `SCENE_ATLAS_READY` on stdout, then warms the CLIP model
3. Runs its scenario logic via `httpx.AsyncClient` + `asyncio`
4. On failure: saves `server.log` + `db.sqlite` to `stress_tests/results/<timestamp>_<name>/`
5. The server is stopped and the next scenario starts clean

No new Python dependencies are required — `httpx` and `Pillow` are already dev deps.

## Scenarios

### 1. `concurrent_imports` — concurrent full import flows

Runs 100 jobs (quick: 10) concurrently, each doing the full flow for 5 (quick: 3) unique images.

**What it catches:** SQLite write-lock contention between the API and the ingest worker, round-robin claiming across jobs, LanceDB write path.

**Pass criteria:** Every job `completed` with all its files `done`, zero HTTP 5xx responses.

---

### 2. `endpoint_spam` — race condition flooding

Fires many concurrent identical requests (100, quick: 20):

1. Cancels of one sealed job → all 200 (cancel is idempotent), job ends `cancelled`
2. Detail polls (`GET /imports/{id}`) → all 200, consistent status
3. `PUT` content to the cancelled job's (now `skipped`) item → all 409
4. Seals of one job → all 200 (seal is idempotent), every response shows the same single group
5. `PUT`s of the same item's bytes → all 200, and the job ends with exactly the expected images

**What it catches:** Non-atomic state transitions, duplicate planning or duplicate imports from retried requests.

**Pass criteria:** No 5xx responses, all the above hold.

---

### 3. `cancellation_chaos` — cancel at every stage

- (a) Before seal (manifest only) → `cancelled`, items `skipped`
- (b) After seal, before any bytes → `cancelled`, items `skipped`
- (c) Right after uploading, while the worker is processing → `cancelled`; once the in-flight batch drains, nothing is left `awaiting_bytes`, `ready` or `processing`
- (d) After completion → 200, the job stays `completed` and its images are kept

**What it catches:** Items left open after a cancel, cancel undoing finished work.

**Pass criteria:** Correct codes and states, no 5xx.

---

### 4. `malformed_input` — corrupted file handling (~2 min)

Puts each malformed fixture (JPEG, PNG, WebP, MP4, WebM: valid magic bytes, corrupt body) into its own job via manifest + `PUT`, and each ZIP (malformed, near-zip-bomb) via `PUT /imports/{id}/archives`. Then seals and waits for the job to finish.

**Expected behaviour:** The corrupt images are rejected by the upload-time content check (`failed`, stage `validate`). The corrupt videos pass it and fail in the worker at the thumbnail stage; they are currently classified `transient`, so each is retried 3 times (about a minute) before failing. A bad ZIP becomes one failed `archive` item (`check_zip_safety()` rejects the near-bomb before extraction).

**What it catches:** Decoder hangs on corrupt data, server crashes, corrupt files being imported.

**Pass criteria:** No 5xx, no timeouts, every job completes, nothing imported.

---

### 5. `large_uploads` — big files, sequential then concurrent

Uploads large video and ZIP files, one at a time and then 5 at once (each in its own job, cancelled afterwards). Skipped in `--quick` mode unless `--large` is also given, which enables the 500 MB+ variants.

**What it catches:** OOM from concurrent streaming, partial state left behind after a 413.

**Pass criteria:** All requests complete or reject cleanly (no 5xx, no timeout).

---

### 6. `concurrent_move_groups` — simultaneous group mutations

Imports images into two groups, then fires 20 concurrent `move-images` requests for the same image IDs.

**What it catches:** Race conditions in the group-assignment logic.

**Pass criteria:** Exactly one move succeeds (200), the rest return 400/404, every image ends up in the target group.

---

### 7. `duplicate_hash_race` — dedup under concurrency

Imports the **same image bytes** in 50 concurrent jobs (quick: 10). Half of them also send the client-side SHA-256 (`POST /hashes`) before uploading, so the client-hint and commit-time dedup paths race.

**What it catches:** Duplicate `Image` rows from concurrent dedup checks.

**Pass criteria:** Every job completes, exactly one copy is imported across all jobs (the rest are `duplicate`), no 5xx.

---

### 8. `server_restart_recovery` — crash recovery

Starts 3 imports (8 files each), uploads all their bytes, SIGKILLs the server while the worker is processing, then starts a new server on the same storage. `IngestWorker.recover()` returns items left `processing` to `ready`.

**What it catches:** Items stuck in `processing` after a crash, imports that never finish after a restart.

**Pass criteria:** Every job reaches `completed` with all its files `done`.

---

### 9. `large_batch_imports` — sustained heavy load

Runs 10 jobs (quick: 2) of 1 000 files each (quick: 100).

**What it catches:** Memory growth under sustained load, embedding throughput, per-file error isolation.

**Pass criteria:** Every job completes with all files `done`, no 5xx.

---

The former `scheduler_interference` scenario was removed: the ingest maintenance task runs every 6 hours, so it never fired during the run and the scenario only repeated `concurrent_imports`. Ingest maintenance is covered by `backend/tests/integration/test_ingest_pipeline.py`.

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
