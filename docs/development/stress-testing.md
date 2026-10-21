# Stress Testing the Import Pipeline

The stress suite (`stress_tests/`) runs the ingest pipeline ([ADR-018](https://github.com/jennis0/scene-atlas/blob/main/design/decisions.md#adr-018-durable-per-item-ingest-pipeline), [design/ingestion.md](https://github.com/jennis0/scene-atlas/blob/main/design/ingestion.md)) against a **real server process**: the live `IngestWorker` thread, SQLite with its single writer, LanceDB and the prepare pool. It covers what the integration tests (which drive the worker synchronously with `drain()`) can't: concurrency at volume, crashes and restarts, and scheduled maintenance running alongside imports.

## Quick start

```bash
# From the repository root
uv run python -m stress_tests list                              # all scenarios
uv run python -m stress_tests generate-fixtures                 # pre-build fixtures (~90 MB)
uv run python -m stress_tests run --scenario happy_path         # one scenario
uv run python -m stress_tests run --scenario undo_import --scenario pause_resume
uv run python -m stress_tests run --all --quick                 # everything, reduced load
uv run python -m stress_tests run --all                         # full load
```

## Requirements

- **An AI model already downloaded.** Every scenario's server gets a fresh data directory, which has no model, and the ingest worker stays system-paused without one. The harness symlinks each model folder from `$STRESS_MODELS_DIR`, or by default `<repo>/data/models`, into the temp data directory (it copies them if symlinks aren't allowed). Run the app once and download a model if that folder is empty.
- **ffmpeg** (optional): only for the real-video controls in `malformed_input`.
- Python dependencies are already in the project (`httpx`, Pillow, numpy).

## Flags

| Flag | Effect |
|------|--------|
| `--quick` | Smaller file counts and concurrency. |
| `--large` | Bigger loads: a 40,000-item manifest (beyond SQLite's 32,766 bound-variable limit), 12,000 px images, a 1,000-image zip, 200 MB corrupt files. Needs a few GB of disk. |

## How it works

Each scenario:
1. Gets a **fresh server process** (`uvicorn backend.app.main:app` on a free port) with its own `APP_DATA_DIR` and `IMAGE_LIBRARY_DIR` under `stress_tests/results/_work_<timestamp>/<scenario>/`. It never touches the repo's `data/` or `images/`.
2. Waits until `GET /health` answers, warms the model with a search, and waits until `GET /imports` reports the queue is not system-paused.
3. Runs the scenario with `httpx.AsyncClient`, using the real upload protocol (design §7):

   ```
   POST /imports → POST /manifest (chunks of ≤2,000) → PUT /archives (optional) → POST /seal
     → POST /hashes (skip known files) → PUT /items/{id}/content (4 in flight)
     → poll GET /imports with If-None-Match until the job settles
   ```

4. Checks results through the API **and** directly against the server's SQLite database and stores (read-only): image rows, stored files, thumbnails, shared content hashes and leftover `.incoming` temp files must agree.
5. Stops the server. On failure, it keeps `server.log` and a DB snapshot.

A job counts as settled when it's `completed`, or `cancelled` with nothing `ready` or `processing`. Any 5xx or transport error fails the scenario.

All fixtures are synthetic: random-noise images, zips of them, and corrupt files. **Never point the suite at real maps**; they're commercial content and the runs must be reproducible.

## Scenarios

| Scenario | What it does | Pass criteria |
|---|---|---|
| `happy_path` | One import of 100 / 500 / 2,000 files; reports setup, upload and processing throughput and how many polls got 304. | All `done`; rows = files = images; no shared hashes |
| `large_manifest` | 5,000 / 10,000 / 40,000 manifest items in 50 groups; re-sends a chunk; seals; pages through every item; uploads a subset, then `finish-upload`. Reports per-step timings. | Re-sent chunk all ignored; 50 groups; subset `done`, rest `skipped` ("Not uploaded"); job `completed` |
| `concurrent_imports` | 10 / 50 / 100 jobs of 5 files, each run end to end at the same time. | Every job `completed` with 5 `done`; no 5xx |
| `round_robin_fairness` | Starts a big job, then four 3-file jobs once it's processing. | Small jobs finish while the big job still has work left |
| `endpoint_spam` | 20 / 100 identical concurrent requests: seal, PUT of one item, manifest after seal, cancel, PUT to a cancelled job, polls with ETag, undo. | Seal idempotent (one group); one image from the PUT race; 409s where expected; one undo succeeds |
| `cancellation_chaos` | Cancel before seal, after seal, mid-processing, and after completion. | Finished work kept, the rest `skipped`, staged files removed; retry on a cancelled job → 409; cancel of a completed job is a no-op |
| `pause_resume` | Pause before bytes arrive, and pause mid-processing. | Nothing claimed while paused (at most one batch finishes); resume completes |
| `reimport_duplicates` | Re-import via client hashes (no bytes sent), via bytes, in-job twins, and the same pixels as differently-compressed PNGs. | All duplicates detected at the right tier; no new images |
| `import_as_copy` | Import-as-copy for hash-skipped duplicates (need an upload) and receipt-detected ones (staged bytes reused). | 3 independent images per file, each with its own stored file |
| `undo_import` | Undo a job that merged into an existing group, a job mid-processing, then the original. | Exactly the job's images, files, thumbnails and created groups removed; the merged-into group kept |
| `retry_failed` | Garbage bytes (fail validation) and corrupt JPEGs (fail in the worker), then retry. | Retry re-opens the job; validation failures go back to `awaiting_bytes` and succeed when re-sent |
| `interrupted_upload_resume` | One client uploads a third and vanishes; a second client lists `awaiting_bytes` items, resumes some, re-PUTs finished ones, then `finish-upload`. | Re-PUT is a no-op; final `done`/`skipped` counts exact |
| `zip_archives` | Small and large zips, a zip with a broken member, junk and a `..` path, a malformed zip and a near zip bomb, plus loose files; an archive after seal. | Bad archives become one failed `archive` item each; the job completes; no path contains `..`; 409 after seal |
| `malformed_input` | Corrupt JPEG/PNG/WebP/MP4/WebM, text named `.png`, a truncated JPEG, an empty upload, a size mismatch, junk files, an oversized manifest entry, and real videos as controls. | Corrupt files `failed` (kind `file`), good files `done`, the job completes, no 5xx |
| `duplicate_hash_race` | The same bytes uploaded to 10 / 50 jobs at once. | Exactly one image |
| `concurrent_move_groups` | 20 concurrent `move-images` for the same images. | Exactly one succeeds |
| `large_uploads` | Four 4,000 px (12,000 px with `--large`) noise JPEGs streamed concurrently; with `--large`, also a 1,000-image zip. | All `done`; reports MB/s |
| `server_restart_recovery` | SIGKILLs the server while a batch is `processing` and a second job is half uploaded, then restarts on the same data. | Nothing `processing` after restart; re-claimed items complete; the half-uploaded job resumes; integrity holds |
| `maintenance_during_import` | Trickles uploads until the scheduler's startup maintenance has run (60 s after start). | No items skipped or lost; the job completes |

## Results and artifacts

Each run writes `stress_tests/results/<timestamp>_run/summary.json`. When a scenario fails:

```
stress_tests/results/<timestamp>_<scenario>/
├── server.log      # backend log (all restarts appended)
├── db.sqlite       # DB snapshot
└── summary.json    # pass/fail, timings, failed checks
```

The work directory (`_work_<timestamp>/`) is deleted when everything passes and kept otherwise. All of `results/` is gitignored.

## Fixtures

Built in `stress_tests/.fixtures/` (gitignored) on first use, and cached by file name. Delete the folder to rebuild. Most scenarios generate small images in memory instead (`fixtures.image_set`, deterministic per seed; use distinct seed ranges for distinct images).

| Fixture | Description |
|---|---|
| `small_10.zip`, `large_100.zip` (`large_1000.zip`) | Zips of noise JPEGs |
| `near_bomb.zip` | 800 × 3 MB of zeros: 2.4 GB declared, about 2.5 MB on disk |
| `malformed_5mb.{jpg,png,webp,mp4,webm,zip}` | Valid magic bytes, random body (200 MB with `--large`) |
| `big_4000px_{0..3}.jpg` | Large valid images (12,000 px with `--large`) |
| `video_640x360_1s.{mp4,webm}` | ffmpeg test pattern (needs ffmpeg) |
