# Stress Testing Framework — Handover Document

**Date:** 2026-03-05
**Branch:** `feature/stress-testing` (worktree at `.worktrees/stress-testing`)
**Status:** Implementation in progress — scaffolding complete, fixtures/scenarios/helpers not yet written

---

## What Has Been Done

### 1. Design & Planning (complete)

- Full design document at `docs/plans/2026-03-05-stress-testing-framework-design.md`
- Plan file at `C:\Users\jenni\.claude\plans\fluffy-plotting-planet.md`
- Design went through brainstorming, a critical peer review (which caught major issues — see below), and was significantly revised

### 2. Key Design Decisions Made

**No Locust.** Import flows are multi-step stateful workflows — Locust is the wrong tool. Use `httpx.AsyncClient` + `asyncio` instead. Zero new dependencies (httpx is already a dev dep).

**Real server subprocess.** Each scenario gets its own fresh uvicorn process with an isolated temp data directory. The server prints `SCENE_ATLAS_READY port=N` to stdout when ready — use that as the startup signal.

**CLIP warm-up gate.** After server ready signal, make a dummy search request with a non-empty query to `/api/v1/search?q=warm+up&limit=1`. This blocks until CLIP is loaded (because `get_clip_service()` calls `_clip_ready.wait()`). Without this, the first N imports all thundering-herd on CLIP load.

**Terminal-first output.** Print `PASS`/`FAIL` immediately to stdout. Save artifacts (server log + DB snapshot) only on failure.

**Small fixtures by default, large behind `--large` flag.** 5MB malformed files exercise the same code paths as 500MB. `--large` enables 500MB+ variants.

**Fresh server per scenario in `--all` mode.** No polluted state.

**Port 0 pattern.** Bind to port 0 to get OS-assigned port, pass via `API_PORT` env var to server. Captured from `SCENE_ATLAS_READY port=N` stdout line.

**`DATA_DIR` env var.** Setting this redirects ALL server paths (images, thumbnails, staging, qdrant, database) to a temp directory. No other path env vars needed.

### 3. Parallel Change Constraint — CRITICAL

**The `docs/plans/2026-03-05-remove-import-confirmation.md` plan is being executed in parallel** and removes the confirmation/review layer. The stress tests MUST NOT use:

| Removed | Don't use |
|---------|-----------|
| `/confirm` single-group endpoint | Use `/confirm-all` only |
| `/finalize` endpoint | Don't call it |
| `/groups/confirm-review` | Don't call it |
| `awaiting_input` job status | Terminal states: `completed`, `failed`, `cancelled` only |
| `pending_groups`, `all_confirmed` fields | Don't read or assert on these |
| `needs_review` image field | Don't read or assert |
| `remaining_groups` in confirm request body | Don't send this field |

**`/confirm-all` IS staying.** The import flow in stress tests is still: `init → upload-batch → analyse → confirm-all → poll until terminal`. Only the UI-facing review gate is gone.

### 4. Package Structure Created

```
stress_tests/                       (at worktree root, not inside backend/)
├── __init__.py                     ✅ written
├── __main__.py                     ✅ written
├── run.py                          ✅ written (see notes on Pyright warnings below)
├── fixtures.py                     ❌ NOT YET WRITTEN
├── scenarios.py                    ❌ NOT YET WRITTEN
├── .fixtures/                      (gitignored, for generated test files)
└── results/                        (gitignored, for failure artifacts)
```

### 5. What `run.py` Contains

- `StressTestServer` class: starts uvicorn subprocess, waits for `SCENE_ATLAS_READY`, warms CLIP, cross-platform shutdown (SIGTERM/SIGKILL on Unix, `taskkill /F /T /PID` on Windows with `CREATE_NEW_PROCESS_GROUP`)
- `RequestStats` dataclass: p50/p95/p99 from a list of timings
- `ScenarioResult` dataclass: pass/fail, message, elapsed, stats, failure_details
- CLI: `run --all`, `run --scenario <name>`, `run --all --quick`, `run --all --large`, `generate-fixtures`, `list`
- Pre-flight checks: disk space warning, ffmpeg detection
- Results collection: saves server log + DB snapshot to `results/<timestamp>_<scenario>/` only on failure

### 6. Pyright Warnings in run.py (non-blocking)

The Pyright errors are expected and non-blocking:
- `Import "httpx" could not be resolved` — httpx is a dev dep, Pyright can't see it without venv configured in IDE
- `Import "stress_tests" could not be resolved` — package will be importable when run via `python -m stress_tests`
- `"readline" is not a known attribute of "None"` (line 211) — `self._proc.stdout` is declared `IO | None` but is always set by Popen; safe to ignore
- `"asdict" is not accessed` — imported but used in `_save_summary`; remove unused import

### 7. `.gitignore` Entries Needed

Add to `.gitignore` in the worktree:
```
stress_tests/.fixtures/
stress_tests/results/
```
These have NOT been added yet.

---

## What Still Needs to Be Done

### Step 2: `fixtures.py` — Fixture Generation

Generate synthetic test files with deterministic seeds (so failures are reproducible).

**Key functions needed:**

```python
def generate_random_noise_jpeg(path: Path, seed: int, width: int, height: int) -> Path:
    """PIL: unique per seed (different SHA-256 hash). width/height varied."""

def generate_random_noise_png(path: Path, seed: int, width: int, height: int) -> Path:
    """PIL: RGBA random noise."""

def generate_random_noise_webp(path: Path, seed: int, width: int, height: int) -> Path:
    """PIL: WebP lossy random noise."""

def generate_zip(images: list[Path], output_path: Path) -> Path:
    """Pack images into a ZIP. Use random-noise JPEGs for realistic compression ratio."""

def generate_near_zip_bomb(output_path: Path) -> Path:
    """Identical compressible PNGs in a ZIP. Tests check_zip_safety() expansion guard."""

def generate_malformed_jpeg(output_path: Path, size_bytes: int) -> Path:
    """Valid JFIF header (FFD8 FF E0 ...) + random garbage body."""

def generate_malformed_png(output_path: Path, size_bytes: int) -> Path:
    """Valid PNG signature (89 50 4E 47 ...) + IHDR chunk + corrupted data."""

def generate_malformed_webp(output_path: Path, size_bytes: int) -> Path:
    """Valid RIFF/WEBP header + corrupted VP8 data."""

def generate_malformed_mp4(output_path: Path, size_bytes: int) -> Path:
    """Valid ftyp box + corrupted moov/mdat."""

def generate_malformed_webm(output_path: Path, size_bytes: int) -> Path:
    """Valid EBML header (1A 45 DF A3) + corrupted data."""

def generate_malformed_zip(output_path: Path, size_bytes: int) -> Path:
    """Valid local file header (PK\x03\x04) + corrupted entries."""

def generate_video_mp4(output_path: Path, duration_seconds: int, resolution: str) -> Path:
    """ffmpeg: color bars, H.264. Requires ffmpeg on PATH."""

def generate_video_webm(output_path: Path, duration_seconds: int, resolution: str) -> Path:
    """ffmpeg: color bars, VP9. Requires ffmpeg on PATH."""

def ensure_fixtures(fixtures_dir: Path, large_mode: bool, has_ffmpeg: bool) -> FixturePaths:
    """Generate all fixtures. Skip if already exist. Return paths dataclass."""
```

**`FixturePaths` dataclass** to return structured paths to all generated fixtures. Scenarios receive this so they don't need to know file names.

**Hash uniqueness:** Random noise JPEGs are inherently unique per seed — different SHA-256 hashes, which is critical because the pipeline's `/check-hashes` deduplication will skip re-uploads of identical files. Each concurrent import must use a different seed range.

**ZIP compression note:** Use random-noise JPEGs inside ZIPs (already entropy-coded, minimal ZIP compression). The near-zip-bomb uses identical compressible PNGs to test the expansion ratio guard in `check_zip_safety()`.

**Default sizes:**
- Malformed files: 5 MB each (same code path as 500MB, 100x less disk)
- With `--large`: 500 MB each
- Large ZIP: 100 images default, 1000 images with `--large`
- Videos: 1s 720p default, 60s 1080p with `--large`

### Step 3: `scenarios.py` — Helpers and Scenarios

**`ImportFlow` async class:**

```python
class ImportFlow:
    def __init__(self, client: httpx.AsyncClient, base_url: str, stats: RequestStats): ...

    async def init_job(self) -> str: ...
    async def upload_batch(self, job_id: str, files: list[tuple[str, bytes, str]],
                           relative_paths: list[str]) -> dict: ...
    async def analyse(self, job_id: str, image_type: str = "battlemap") -> dict: ...
    async def confirm_all(self, job_id: str, groups: list[dict]) -> dict: ...
    async def cancel(self, job_id: str) -> dict: ...
    async def get_status(self, job_id: str) -> dict: ...
    async def wait_for_terminal(self, job_id: str, timeout: float = 120.0) -> dict: ...
    async def full_import(self, images: list[tuple[str, bytes]],
                          image_type: str = "battlemap") -> dict:
        """Run complete init→upload→analyse→confirm-all→poll flow."""
```

**CRITICAL — `confirm_all` body shape:**
```python
# Do NOT include remaining_groups (being removed by parallel plan)
body = {
    "groups": [
        {
            "author": group["author"],
            "group_name": group["group_name"],
            "files": [
                {
                    "relative_path": f["relative_path"],
                    "name": f.get("filename", ""),
                    "media_type": "image/jpeg",
                    "image_type": image_type,
                    "tags": [],
                }
                for f in group["files"]
            ],
            # NO remaining_groups field
        }
        for group in groups
    ]
}
```

**`generate_unique_images(count, base_seed, format="JPEG")` helper:**
- Returns list of `(relative_path, bytes_data)` tuples
- Each image has a unique seed so each has a unique SHA-256
- Relative paths follow the convention `StressAuthor/StressMap/image_{i}.jpg` so the grouping logic detects them as one group

**`SCENARIO_REGISTRY`:** list of `(name, fn, default_time_estimate, quick_time_estimate)` tuples, imported by `run.py`.

**The 10 scenarios** (see plan for full spec), in priority implementation order:

1. `concurrent_imports` — 100 coroutines each doing a full import (5 images). Quick: 10 jobs/3 images. Pass: all terminal, 0 HTTP 500s, no zombie jobs.

2. `endpoint_spam` — Create 1 job, then fire 100 concurrent cancels → expect first 200 rest 409/404; 100 concurrent status polls → consistent data; 100 concurrent uploads to completed job → all 409; 100 concurrent confirm-all to staging job → at most one succeeds (race condition test). **Use `/confirm-all` ONLY, never `/confirm`.**

3. `cancellation_chaos` — Start 4 imports, cancel at: (a) during upload before analyse; (b) during analysis; (c) after confirm-all while processing; (d) after `completed`. Check status codes and terminal states. **Do NOT test cancellation from `awaiting_input` — that state is being removed.**

4. `malformed_input` — Upload each malformed fixture (JPEG, PNG, WebP, MP4, WebM, ZIP) + near-zip-bomb. Each upload should return 200 (file skipped with warning in response) or 413 (zip bomb). No 500s, no hangs (30s timeout per request).

5. `large_uploads` — Upload large files one at a time: MP4, WebM, ZIP. Then 5 concurrent large uploads. Accept or reject cleanly, no OOM, no partial state.

6. `concurrent_move_groups` — Import images into 3 groups, then fire 20 concurrent move-group requests for the same images. Expect exactly one move per image to succeed, rest 409/400/404.

7. `duplicate_hash_race` — Upload the SAME image bytes to 50 concurrent import jobs. Dedup logic should produce correct results (no duplicate Image rows with same content_hash).

8. `server_restart_recovery` — Start 3 imports, force-kill server, restart, verify `mark_interrupted_jobs()` moved all in-flight jobs to "broken". No stuck jobs in active/uploading.

9. `large_batch_imports` — 10 jobs × 1000 files (batches of 50). Quick: 2 × 100. Long running.

10. `scheduler_interference` — 20 concurrent imports while the scheduler's maintenance tasks are running. Verify no staging dirs cleaned up prematurely, no active jobs expired.

### Step 4: `.gitignore` Update

Add to root `.gitignore`:
```
stress_tests/.fixtures/
stress_tests/results/
```

### Step 5: Verification Steps

```bash
# From worktree root (.worktrees/stress-testing)
python -m stress_tests list
python -m stress_tests generate-fixtures
python -m stress_tests run --scenario endpoint_spam --quick
python -m stress_tests run --all --quick
```

### Step 6: Commit and PR

Follow CLAUDE.md: run ruff format/check on Python code, commit, then use `superpowers:finishing-a-development-branch` to present options.

---

## Key Files to Read Before Starting

- `backend/app/config.py` — `Settings` class, how `DATA_DIR` env var redirects all paths
- `backend/app/main.py` — server startup sequence, `SCENE_ATLAS_READY` stdout signal (line 117), CLIP background load (line 74)
- `backend/app/api/imports.py` — all endpoint shapes; `ImportConfirmAllRequest` class (line 63); endpoint at line 714
- `backend/app/models/schemas.py` — `ImportConfirmRequest` (line 425), `ImportConfirmFile` (line 406)
- `backend/app/services/clip_service.py` — `_clip_ready` event, `start_clip_background_load()`
- `backend/app/api/groups.py` — move-group endpoint for `concurrent_move_groups` scenario
- `backend/tests/conftest.py` — existing test patterns for reference
- `backend/tests/integration/test_upload_endpoint.py` — how multipart uploads are constructed in tests

## Already-Written Files to NOT Overwrite

- `stress_tests/__init__.py`
- `stress_tests/__main__.py`
- `stress_tests/run.py`
- `docs/plans/2026-03-05-stress-testing-framework-design.md`

---

## How to Start

```bash
cd /c/Users/jenni/Code/scene-atlas/.worktrees/stress-testing
git status  # Should show stress_tests/ files as new
```

Use `superpowers:executing-plans` skill and reference `C:\Users\jenni\.claude\plans\fluffy-plotting-planet.md`. Start from Step 2 (fixtures.py). The scaffold is ready.
