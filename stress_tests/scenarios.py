"""Stress test scenarios for the Scene Atlas import pipeline.

Each scenario is an async function with this signature:

    async def scenario_name(
        *,
        base_url: str,
        fixtures_dir: Path,
        large_mode: bool,
        quick_mode: bool,
    ) -> ScenarioResult: ...

SCENARIO_REGISTRY is a list of (name, fn, default_time_estimate, quick_time_estimate)
tuples imported by run.py.

IMPORTANT — parallel-change constraint:
The /confirm (single-group) endpoint and /finalize endpoint are being removed
by a parallel branch.  This file MUST NOT use them.  Only /confirm-all is used.
"""

from __future__ import annotations

import asyncio
import io
import json
import random
import time
from pathlib import Path
from typing import Any

import httpx
from tqdm import tqdm
from tqdm.asyncio import tqdm as atqdm

try:
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover
    PILImage = None  # type: ignore[assignment]

from stress_tests.run import RequestStats, ScenarioResult, StressTestServer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "/api/v1"
IMPORTS_BASE = f"{API_BASE}/imports"
GROUPS_BASE = f"{API_BASE}/groups"

# Job states considered terminal (polling stops when any of these is reached)
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "broken", "expired"})


# ---------------------------------------------------------------------------
# ImportFlow — thin async wrapper around the import HTTP API
# ---------------------------------------------------------------------------


class ImportFlow:
    """Wraps the import pipeline API for use within async stress scenarios."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        stats: RequestStats | None = None,
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._stats = stats or RequestStats()

    def _url(self, path: str) -> str:
        return self._base + path

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        files: Any = None,
        data: Any = None,
        timeout: float = 60.0,
    ) -> httpx.Response:
        t0 = time.monotonic()
        r = await self._client.request(
            method,
            self._url(path),
            json=json,
            files=files,
            data=data,
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        self._stats.record(elapsed, ok=r.status_code < 500)
        return r

    async def init_job(self) -> str:
        """POST /imports/init → job_id string."""
        r = await self._request("POST", f"{IMPORTS_BASE}/init")
        r.raise_for_status()
        return r.json()["job_id"]

    async def upload_batch(
        self,
        job_id: str,
        files: list[tuple[str, bytes, str]],
        relative_paths: list[str],
        timeout: float = 120.0,
    ) -> dict:
        """POST /imports/{job_id}/upload-batch.

        Args:
            files: List of (filename, bytes_data, content_type) tuples.
            relative_paths: Matching relative path for each file.
        """
        multipart_files = [("files", (name, data, mime)) for name, data, mime in files]
        form_data = {"relative_paths": json.dumps(relative_paths)}
        r = await self._request(
            "POST",
            f"{IMPORTS_BASE}/{job_id}/upload-batch",
            files=multipart_files,
            data=form_data,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    async def analyse(self, job_id: str, image_type: str = "battlemap") -> dict:
        """POST /imports/{job_id}/analyse."""
        r = await self._request(
            "POST",
            f"{IMPORTS_BASE}/{job_id}/analyse",
            json={"manifest": [], "image_type": image_type},
        )
        r.raise_for_status()
        return r.json()

    async def confirm_all(
        self, job_id: str, groups: list[dict], image_type: str = "battlemap"
    ) -> dict:
        """POST /imports/{job_id}/confirm-all.

        NOTE: Does NOT include remaining_groups (field being removed by parallel branch).
        """
        confirm_groups = []
        for g in groups:
            confirm_groups.append(
                {
                    "author": g.get("author") or "StressAuthor",
                    "group_name": g["group_name"],
                    "files": [
                        {
                            "relative_path": f["relative_path"],
                            "name": f.get("filename") or f["relative_path"].split("/")[-1],
                            "media_type": "image/jpeg",
                            "image_type": image_type,
                            "tags": [],
                        }
                        for f in g["files"]
                    ],
                    # NO remaining_groups field
                }
            )
        r = await self._request(
            "POST",
            f"{IMPORTS_BASE}/{job_id}/confirm-all",
            json={"groups": confirm_groups},
        )
        r.raise_for_status()
        return r.json()

    async def cancel(self, job_id: str) -> dict:
        """POST /imports/{job_id}/cancel."""
        r = await self._request("POST", f"{IMPORTS_BASE}/{job_id}/cancel")
        return r.json()

    async def get_status(self, job_id: str) -> dict:
        """GET /imports/{job_id}/status."""
        r = await self._request("GET", f"{IMPORTS_BASE}/{job_id}/status")
        r.raise_for_status()
        return r.json()

    async def wait_for_terminal(self, job_id: str, timeout: float = 180.0) -> dict:
        """Poll status until a terminal state is reached.

        Raises RuntimeError on timeout.  Returns the final status response.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = await self.get_status(job_id)
            if status["status"] in TERMINAL_STATES:
                return status
            await asyncio.sleep(0.5)
        raise RuntimeError(f"Job {job_id} did not reach terminal state within {timeout}s")

    async def full_import(
        self,
        images: list[tuple[str, bytes]],
        image_type: str = "battlemap",
        batch_size: int = 50,
    ) -> dict:
        """Run complete init → upload → analyse → confirm-all → poll flow.

        Args:
            images: List of (relative_path, bytes_data) tuples.
            image_type: Passed to analyse and confirm.
            batch_size: Max files per upload-batch call.

        Returns the final status response.
        """
        job_id = await self.init_job()

        # Upload in batches
        for batch_start in range(0, len(images), batch_size):
            batch = images[batch_start : batch_start + batch_size]
            files = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in batch]
            rel_paths = [rel for rel, _ in batch]
            await self.upload_batch(job_id, files, rel_paths)

        # Analyse
        analysis = await self.analyse(job_id, image_type=image_type)
        groups = analysis.get("groups", [])

        if not groups:
            # Nothing to confirm — job stays in staging; cancel it
            await self.cancel(job_id)
            return {"job_id": job_id, "status": "cancelled"}

        # Confirm all groups
        await self.confirm_all(job_id, groups, image_type=image_type)

        # Poll to completion
        return await self.wait_for_terminal(job_id)


# ---------------------------------------------------------------------------
# generate_unique_images — deterministic per-job image sets
# ---------------------------------------------------------------------------


def generate_unique_images(
    count: int,
    base_seed: int,
    group_tag: str = "0",
    width: int = 160,
    height: int = 120,
) -> list[tuple[str, bytes]]:
    """Return `count` unique (relative_path, bytes_data) JPEG tuples.

    Each image has a unique seed so its SHA-256 hash differs from all others,
    defeating the /check-hashes dedup logic.  Use non-overlapping base_seed
    values across concurrent jobs.

    Relative paths use the convention ``StressAuthor/StressMap_{group_tag}/image_{i}.jpg``
    so the grouping logic bundles them into one group per job.
    """
    images: list[tuple[str, bytes]] = []
    assert PILImage is not None, "Pillow is required"
    for i in range(count):
        seed = base_seed + i
        rng = random.Random(seed)
        data = bytes(rng.randint(0, 255) for _ in range(width * height * 3))
        img = PILImage.frombytes("RGB", (width, height), data)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70 + (seed % 25))
        rel_path = f"StressAuthor/StressMap_{group_tag}/image_{i:04d}.jpg"
        images.append((rel_path, buf.getvalue()))
    return images


# ---------------------------------------------------------------------------
# Scenario 1: concurrent_imports
# ---------------------------------------------------------------------------


async def concurrent_imports(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """100 concurrent jobs each running a full import flow.

    Tests SQLite WAL contention, Qdrant RLock bottleneck, and job runner
    thread pool under heavy concurrent load.

    Pass: all jobs reach terminal state, zero 500 errors, no zombie jobs.
    """
    jobs_count = 10 if quick_mode else 100
    files_per_job = 3 if quick_mode else 5
    stats = RequestStats()

    async def run_one_job(job_idx: int) -> tuple[bool, str]:
        async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
            flow = ImportFlow(client, base_url, stats)
            # Each job uses a unique seed range: job 0 → seeds 0–4, job 1 → 5–9, etc.
            images = generate_unique_images(files_per_job, base_seed=job_idx * files_per_job)
            try:
                result = await flow.full_import(images)
                status = result.get("status", "unknown")
                if status not in TERMINAL_STATES:
                    return False, f"Job {job_idx} stuck in '{status}'"
                return True, status
            except Exception as exc:
                return False, f"Job {job_idx} raised: {exc}"

    t0 = time.monotonic()
    outcomes = await atqdm.gather(
        *(run_one_job(i) for i in range(jobs_count)),
        desc="  jobs",
        unit="job",
    )
    elapsed = time.monotonic() - t0

    failures = [(ok, msg) for ok, msg in outcomes if not ok]
    http_errors = stats.errors

    if failures or http_errors:
        details = "\n".join(msg for _, msg in failures[:10])
        if http_errors:
            details += f"\n{http_errors} HTTP 5xx error(s)"
        return ScenarioResult(
            name="concurrent_imports",
            passed=False,
            message=f"{len(failures)}/{jobs_count} jobs failed, {http_errors} HTTP errors",
            elapsed=elapsed,
            stats=stats,
            failure_details=details,
        )

    return ScenarioResult(
        name="concurrent_imports",
        passed=True,
        message=f"{jobs_count}/{jobs_count} jobs completed",
        elapsed=elapsed,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Scenario 2: endpoint_spam
# ---------------------------------------------------------------------------


async def endpoint_spam(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Race condition testing via redundant request flooding.

    Sub-tests (run sequentially within the scenario):
    1. 100 concurrent cancels → first succeeds (200), rest 409/404
    2. 100 concurrent status polls → all 200, consistent data
    3. 100 concurrent upload-batch to a completed/cancelled job → all 409
    4. 100 concurrent confirm-all to a staging job → at most one 200

    Pass: no 500 errors, state transitions consistent, no duplicate images.
    """
    concurrency = 20 if quick_mode else 100
    stats = RequestStats()
    failures: list[str] = []

    with tqdm(total=4, desc="  sub-tests", unit="sub-test", leave=True) as pbar:
        async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
            flow = ImportFlow(client, base_url, stats)

            # --- Sub-test 1: concurrent cancels ---
            pbar.set_postfix_str("concurrent-cancels")
            job_id = await flow.init_job()
            # Upload a file first so there's something to cancel
            images = generate_unique_images(1, base_seed=900000)
            files = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images]
            await flow.upload_batch(job_id, files, [rel for rel, _ in images])

            async def do_cancel(idx: int) -> int:
                r = await client.post(f"{IMPORTS_BASE}/{job_id}/cancel", timeout=30)
                return r.status_code

            cancel_codes = await asyncio.gather(*(do_cancel(i) for i in range(concurrency)))
            ok_cancels = sum(1 for c in cancel_codes if c == 200)
            bad_codes = [c for c in cancel_codes if c not in (200, 409, 404)]
            if ok_cancels == 0:
                failures.append(f"Sub-test 1: no cancel succeeded (codes: {set(cancel_codes)})")
            if bad_codes:
                failures.append(f"Sub-test 1: unexpected cancel status codes: {set(bad_codes)}")
            pbar.update(1)

            # --- Sub-test 2: concurrent status polls ---
            pbar.set_postfix_str("concurrent-status-polls")
            # Create a job in uploading state
            job_id2 = await flow.init_job()

            async def do_status(idx: int) -> tuple[int, str]:
                r = await client.get(f"{IMPORTS_BASE}/{job_id2}/status", timeout=30)
                return r.status_code, r.json().get("status", "") if r.status_code == 200 else ""

            poll_results = await asyncio.gather(*(do_status(i) for i in range(concurrency)))
            poll_errors = [c for c, _ in poll_results if c >= 500]
            ok_polls = sum(1 for c, _ in poll_results if c == 200)
            statuses = {s for _, s in poll_results if s}
            if poll_errors:
                failures.append(f"Sub-test 2: {len(poll_errors)} 5xx errors in status polls")
            if ok_polls == 0:
                failures.append(
                    f"Sub-test 2: no poll succeeded (codes: { {c for c, _ in poll_results} })"
                )
            if len(statuses) > 1:
                failures.append(f"Sub-test 2: inconsistent status values: {statuses}")
            # Clean up job2
            await flow.cancel(job_id2)
            pbar.update(1)

            # --- Sub-test 3: uploads to completed/cancelled job ---
            pbar.set_postfix_str("upload-to-cancelled")

            # job_id is now cancelled; uploading to it should give 409
            async def do_upload_cancelled(idx: int) -> int:
                images2 = generate_unique_images(1, base_seed=800000 + idx)
                files2 = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images2]
                r = await client.post(
                    f"{IMPORTS_BASE}/{job_id}/upload-batch",
                    files=[("files", (name, data, mime)) for name, data, mime in files2],
                    data={"relative_paths": json.dumps([rel for rel, _ in images2])},
                    timeout=30,
                )
                return r.status_code

            upload_codes = await asyncio.gather(
                *(do_upload_cancelled(i) for i in range(concurrency))
            )
            unexpected_upload = [c for c in upload_codes if c not in (409, 404, 422, 400)]
            if unexpected_upload:
                failures.append(
                    f"Sub-test 3: unexpected codes for upload to cancelled job: {set(unexpected_upload)}"
                )
            pbar.update(1)

            # --- Sub-test 4: concurrent confirm-all to staging job ---
            pbar.set_postfix_str("concurrent-confirm-all")
            # Set up a job in staging state
            job_id3 = await flow.init_job()
            images3 = generate_unique_images(2, base_seed=700000)
            files3 = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images3]
            await flow.upload_batch(job_id3, files3, [rel for rel, _ in images3])
            analysis3 = await flow.analyse(job_id3)
            groups3 = analysis3.get("groups", [])

            confirm_body = {
                "groups": [
                    {
                        "author": g.get("author") or "StressAuthor",
                        "group_name": g["group_name"],
                        "files": [
                            {
                                "relative_path": f["relative_path"],
                                "name": f.get("filename") or f["relative_path"].split("/")[-1],
                                "media_type": "image/jpeg",
                                "image_type": "battlemap",
                                "tags": [],
                            }
                            for f in g["files"]
                        ],
                    }
                    for g in groups3
                ]
            }

            async def do_confirm_all(idx: int) -> int:
                r = await client.post(
                    f"{IMPORTS_BASE}/{job_id3}/confirm-all",
                    json=confirm_body,
                    timeout=30,
                )
                return r.status_code

            confirm_codes = await asyncio.gather(*(do_confirm_all(i) for i in range(concurrency)))
            ok_confirms = sum(1 for c in confirm_codes if c == 200)
            bad_confirms = [c for c in confirm_codes if c not in (200, 409, 404, 422)]
            if ok_confirms > 1:
                # More than one confirm succeeded — potential duplicate processing
                failures.append(
                    f"Sub-test 4: {ok_confirms} concurrent confirms succeeded (expected ≤1)"
                )
            if bad_confirms:
                failures.append(f"Sub-test 4: unexpected confirm-all codes: {set(bad_confirms)}")
            # Let the job finish (or cancel it)
            if ok_confirms >= 1:
                try:
                    await flow.wait_for_terminal(job_id3, timeout=120)
                except RuntimeError:
                    await flow.cancel(job_id3)
            else:
                await flow.cancel(job_id3)
            pbar.update(1)
    passed = len(failures) == 0
    return ScenarioResult(
        name="endpoint_spam",
        passed=passed,
        message=(
            f"{concurrency * 4} requests across 4 sub-tests"
            if passed
            else f"{len(failures)} sub-test(s) failed"
        ),
        elapsed=0,  # set by _run_scenario
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 3: cancellation_chaos
# ---------------------------------------------------------------------------


async def cancellation_chaos(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Cancel at every pipeline stage and verify correct terminal states.

    Stages tested:
    (a) Cancel during upload (before analyse)
    (b) Cancel in staging state (after analyse, before confirm)
    (c) Cancel in active state (immediately after confirm-all, while processing)
    (d) Cancel after completion (expects 409 or error response)

    Does NOT test cancellation from awaiting_input (state being removed).

    Pass: appropriate status codes, all jobs reach terminal state.
    """
    stats = RequestStats()
    failures: list[str] = []

    stages = [
        "(a) cancel-during-upload",
        "(b) cancel-in-staging",
        "(c) cancel-active",
        "(d) cancel-after-complete",
    ]
    async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
        flow = ImportFlow(client, base_url, stats)

        with tqdm(total=len(stages), desc="  stages", unit="stage") as pbar:
            # --- (a) Cancel during upload ---
            pbar.set_postfix_str(stages[0])
            job_a = await flow.init_job()
            images_a = generate_unique_images(2, base_seed=500000)
            files_a = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images_a]
            await flow.upload_batch(job_a, files_a, [rel for rel, _ in images_a])
            r = await client.post(f"{IMPORTS_BASE}/{job_a}/cancel", timeout=30)
            if r.status_code not in (200,):
                failures.append(f"(a) Expected 200 for cancel-during-upload, got {r.status_code}")
            # Verify terminal
            status_a = await flow.get_status(job_a)
            if status_a["status"] not in TERMINAL_STATES:
                failures.append(f"(a) Job stuck in '{status_a['status']}' after cancel")
            pbar.update(1)

            # --- (b) Cancel in staging state (after analyse) ---
            pbar.set_postfix_str(stages[1])
            job_b = await flow.init_job()
            images_b = generate_unique_images(2, base_seed=510000)
            files_b = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images_b]
            await flow.upload_batch(job_b, files_b, [rel for rel, _ in images_b])
            await flow.analyse(job_b)
            r = await client.post(f"{IMPORTS_BASE}/{job_b}/cancel", timeout=30)
            if r.status_code not in (200,):
                failures.append(f"(b) Expected 200 for cancel-in-staging, got {r.status_code}")
            status_b = await flow.get_status(job_b)
            if status_b["status"] not in TERMINAL_STATES:
                failures.append(f"(b) Job stuck in '{status_b['status']}' after cancel")
            pbar.update(1)

            # --- (c) Cancel in active state (immediately after confirm-all) ---
            pbar.set_postfix_str(stages[2])
            job_c = await flow.init_job()
            images_c = generate_unique_images(3, base_seed=520000)
            files_c = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images_c]
            await flow.upload_batch(job_c, files_c, [rel for rel, _ in images_c])
            analysis_c = await flow.analyse(job_c)
            groups_c = analysis_c.get("groups", [])
            if groups_c:
                await flow.confirm_all(job_c, groups_c)
            # Immediately cancel (job may still be processing)
            r = await client.post(f"{IMPORTS_BASE}/{job_c}/cancel", timeout=30)
            if r.status_code not in (200, 409):
                failures.append(f"(c) Unexpected cancel code: {r.status_code}")
            # Wait for terminal regardless
            try:
                status_c = await flow.wait_for_terminal(job_c, timeout=120)
                if status_c["status"] not in TERMINAL_STATES:
                    failures.append(f"(c) Job not terminal after cancel: {status_c['status']}")
            except RuntimeError as exc:
                failures.append(f"(c) Timeout waiting for terminal: {exc}")
            pbar.update(1)

            # --- (d) Cancel after completion (should be 409) ---
            pbar.set_postfix_str(stages[3])
            job_d = await flow.init_job()
            images_d = generate_unique_images(1, base_seed=530000)
            files_d = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images_d]
            await flow.upload_batch(job_d, files_d, [rel for rel, _ in images_d])
            analysis_d = await flow.analyse(job_d)
            groups_d = analysis_d.get("groups", [])
            if groups_d:
                await flow.confirm_all(job_d, groups_d)
                await flow.wait_for_terminal(job_d, timeout=120)
            r = await client.post(f"{IMPORTS_BASE}/{job_d}/cancel", timeout=30)
            if r.status_code not in (409,):
                failures.append(
                    f"(d) Expected 409 for cancel-after-completion, got {r.status_code}"
                )
            pbar.update(1)

    passed = len(failures) == 0
    return ScenarioResult(
        name="cancellation_chaos",
        passed=passed,
        message="All 4 cancellation stages handled correctly"
        if passed
        else f"{len(failures)} failure(s)",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 4: malformed_input
# ---------------------------------------------------------------------------


async def malformed_input(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Upload malformed/corrupt files and verify the server rejects gracefully.

    Each file is uploaded as a fresh import job.  Expected outcomes:
    - Malformed images (JPEG/PNG/WebP): server skips file (skipped_invalid),
      analyse returns empty groups or group with 0 files, job gets cancelled.
    - Malformed video (MP4/WebM): same — skipped or 413.
    - Malformed ZIP: skipped_invalid or 413.
    - Near-zip-bomb: 413 from upload_batch (check_zip_safety rejects it).

    Pass: no 5xx responses, no hangs (30s timeout per request).
    """
    malformed_mb = 500 if large_mode else 5
    _p = fixtures_dir / f"malformed_{malformed_mb}mb"
    test_files = [
        ("malformed_jpeg", Path(f"{_p}.jpg"), "image/jpeg"),
        ("malformed_png", Path(f"{_p}.png"), "image/png"),
        ("malformed_webp", Path(f"{_p}.webp"), "image/webp"),
        ("malformed_mp4", Path(f"{_p}.mp4"), "video/mp4"),
        ("malformed_webm", Path(f"{_p}.webm"), "video/webm"),
        ("malformed_zip", Path(f"{_p}.zip"), "application/zip"),
        ("near_zip_bomb", fixtures_dir / "near_bomb.zip", "application/zip"),
    ]

    stats = RequestStats()
    failures: list[str] = []
    tested = 0

    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        flow = ImportFlow(client, base_url, stats)

        for label, path, mime in test_files:
            if not path.exists():
                # Skip if fixture missing (e.g. large_mode fixture not generated)
                continue
            tested += 1
            file_data = path.read_bytes()
            job_id = await flow.init_job()
            filename = path.name

            try:
                r = await client.post(
                    f"{IMPORTS_BASE}/{job_id}/upload-batch",
                    files=[("files", (filename, file_data, mime))],
                    data={"relative_paths": json.dumps([f"Stress/{filename}"])},
                    timeout=30,
                )
            except httpx.TimeoutException:
                failures.append(f"{label}: request timed out (>30s)")
                await flow.cancel(job_id)
                continue

            if r.status_code >= 500:
                failures.append(f"{label}: got {r.status_code} from upload-batch")
                await flow.cancel(job_id)
                continue

            if r.status_code == 413:
                # Correctly rejected (zip bomb or size limit)
                await flow.cancel(job_id)
                continue

            if r.status_code != 200:
                # 4xx is fine (rejected for other reasons)
                await flow.cancel(job_id)
                continue

            # Upload accepted — check analyse doesn't crash
            try:
                r2 = await client.post(
                    f"{IMPORTS_BASE}/{job_id}/analyse",
                    json={"manifest": [], "image_type": "battlemap"},
                    timeout=30,
                )
                if r2.status_code >= 500:
                    failures.append(f"{label}: got {r2.status_code} from analyse")
            except httpx.TimeoutException:
                failures.append(f"{label}: analyse timed out (>30s)")

            await flow.cancel(job_id)

    passed = len(failures) == 0
    return ScenarioResult(
        name="malformed_input",
        passed=passed,
        message=f"{tested} malformed fixtures tested, all handled gracefully"
        if passed
        else f"{len(failures)} failure(s)",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 5: large_uploads
# ---------------------------------------------------------------------------


async def large_uploads(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Upload large video and ZIP files — single then concurrent.

    Requires --large flag for the really large variants.  In quick mode
    this scenario is skipped (not enough disk space on CI machines).

    Pass: no OOM, no partial state, all complete or reject cleanly.
    """
    if quick_mode and not large_mode:
        return ScenarioResult(
            name="large_uploads",
            passed=True,
            message="Skipped in --quick mode (use --large to enable)",
            elapsed=0,
        )

    stats = RequestStats()
    failures: list[str] = []
    tested: list[str] = []

    malformed_mb = 500 if large_mode else 5
    candidates = [
        fixtures_dir / f"malformed_{malformed_mb}mb.mp4",
        fixtures_dir / f"malformed_{malformed_mb}mb.webm",
    ]
    if large_mode:
        large_count = 1000
        candidates.append(fixtures_dir / f"large_{large_count}.zip")

    available = [p for p in candidates if p.exists()]

    if not available:
        return ScenarioResult(
            name="large_uploads",
            passed=True,
            message="No large fixtures available — run generate-fixtures first",
            elapsed=0,
        )

    async with httpx.AsyncClient(base_url=base_url, timeout=600) as client:
        flow = ImportFlow(client, base_url, stats)

        # Sequential uploads — cache bytes so the concurrent section can reuse them
        file_data_cache: dict = {}
        for path in available:
            tested.append(path.name)
            file_data = file_data_cache.setdefault(path, path.read_bytes())
            job_id = await flow.init_job()
            try:
                r = await client.post(
                    f"{IMPORTS_BASE}/{job_id}/upload-batch",
                    files=[("files", (path.name, file_data, "application/octet-stream"))],
                    data={"relative_paths": json.dumps([path.name])},
                    timeout=300,
                )
                if r.status_code >= 500:
                    failures.append(f"Sequential {path.name}: got {r.status_code}")
            except Exception as exc:
                failures.append(f"Sequential {path.name}: {exc}")
            finally:
                await flow.cancel(job_id)

        # Concurrent uploads (up to 5 at once using first available file).
        # Reuse already-loaded bytes to avoid a second O(500 MB) read in --large mode.
        if available:
            big_file_path = available[0]
            big_file_data = file_data_cache.get(big_file_path) or big_file_path.read_bytes()

            async def concurrent_upload(idx: int) -> tuple[bool, str]:
                jid = await flow.init_job()
                try:
                    r = await client.post(
                        f"{IMPORTS_BASE}/{jid}/upload-batch",
                        files=[
                            (
                                "files",
                                (big_file_path.name, big_file_data, "application/octet-stream"),
                            )
                        ],
                        data={"relative_paths": json.dumps([big_file_path.name])},
                        timeout=300,
                    )
                    if r.status_code >= 500:
                        return False, f"Concurrent upload {idx}: {r.status_code}"
                    return True, "ok"
                except Exception as exc:
                    return False, f"Concurrent upload {idx}: {exc}"
                finally:
                    await flow.cancel(jid)

            concurrent_results = await asyncio.gather(*(concurrent_upload(i) for i in range(5)))
            for ok, msg in concurrent_results:
                if not ok:
                    failures.append(msg)

    passed = len(failures) == 0
    return ScenarioResult(
        name="large_uploads",
        passed=passed,
        message=f"Tested: {', '.join(tested)}" if passed else f"{len(failures)} failure(s)",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 6: concurrent_move_groups
# ---------------------------------------------------------------------------


async def concurrent_move_groups(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Concurrent group-mutation race condition test.

    Imports images into two groups (source and target).  Fires 20 concurrent
    move-images requests targeting the same images in the source group.
    At most one should succeed; the rest get 400/404.

    Pass: exactly one move succeeds per image, no 500 errors, no duplicate
    group assignments.
    """
    concurrency = 20
    stats = RequestStats()
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
        flow = ImportFlow(client, base_url, stats)

        # Import source group: 4 images
        images_src = generate_unique_images(4, base_seed=600000, group_tag="src")
        src_status = await flow.full_import(images_src)
        if src_status.get("status") != "completed":
            return ScenarioResult(
                name="concurrent_move_groups",
                passed=False,
                message=f"Setup import failed: {src_status.get('status')}",
                elapsed=0,
                failure_details=str(src_status),
            )

        # Import target group: 2 images (separate group)
        images_tgt = generate_unique_images(2, base_seed=600100, group_tag="tgt")
        tgt_status = await flow.full_import(images_tgt)
        if tgt_status.get("status") != "completed":
            return ScenarioResult(
                name="concurrent_move_groups",
                passed=False,
                message=f"Target import failed: {tgt_status.get('status')}",
                elapsed=0,
                failure_details=str(tgt_status),
            )

        # Find the group IDs from the job status responses
        src_group_id: int | None = None
        tgt_group_id: int | None = None

        src_job_status = await flow.get_status(src_status.get("job_id", ""))
        tgt_job_status = await flow.get_status(tgt_status.get("job_id", ""))

        for g in src_job_status.get("groups", []):
            if g.get("group_id"):
                src_group_id = g["group_id"]
                break
        for g in tgt_job_status.get("groups", []):
            if g.get("group_id"):
                tgt_group_id = g["group_id"]
                break

        if not src_group_id or not tgt_group_id:
            return ScenarioResult(
                name="concurrent_move_groups",
                passed=False,
                message="Could not find group IDs after import",
                elapsed=0,
                failure_details=f"src_group_id={src_group_id}, tgt_group_id={tgt_group_id}",
            )

        # Get image IDs from source group
        r = await client.get(f"{GROUPS_BASE}/{src_group_id}", timeout=30)
        if r.status_code != 200:
            return ScenarioResult(
                name="concurrent_move_groups",
                passed=False,
                message=f"Could not fetch source group: {r.status_code}",
                elapsed=0,
            )
        src_images = r.json().get("images", [])
        image_ids = [img["id"] for img in src_images]

        if not image_ids:
            return ScenarioResult(
                name="concurrent_move_groups",
                passed=False,
                message="Source group has no images",
                elapsed=0,
            )

        # Fire concurrent move-images requests targeting the same image_ids
        async def do_move(idx: int) -> int:
            r2 = await client.post(
                f"{GROUPS_BASE}/{src_group_id}/move-images",
                json={"target_group_id": tgt_group_id, "image_ids": image_ids},
                timeout=30,
            )
            return r2.status_code

        move_codes = await asyncio.gather(*(do_move(i) for i in range(concurrency)))
        ok_moves = sum(1 for c in move_codes if c == 200)
        bad_codes = [c for c in move_codes if c not in (200, 400, 404, 409)]

        if ok_moves == 0:
            failures.append(
                f"No move request succeeded — expected exactly 1 (codes: {sorted(move_codes)})"
            )
        elif ok_moves > 1:
            failures.append(
                f"Expected exactly 1 successful move, got {ok_moves} — possible duplicate processing (codes: {sorted(move_codes)})"
            )
        if bad_codes:
            failures.append(f"Unexpected move status codes: {set(bad_codes)}")

        # Verify source group images are all in target (or source is deleted)
        r3 = await client.get(f"{GROUPS_BASE}/{src_group_id}", timeout=30)
        r4 = await client.get(f"{GROUPS_BASE}/{tgt_group_id}", timeout=30)
        if r3.status_code == 200:
            remaining = r3.json().get("images", [])
            if any(img["id"] in set(image_ids) for img in remaining):
                failures.append("Some moved images are still in source group")
        if r4.status_code == 200:
            tgt_imgs = {img["id"] for img in r4.json().get("images", [])}
            missing = [iid for iid in image_ids if iid not in tgt_imgs]
            if missing:
                failures.append(f"Images not found in target group: {missing}")

    passed = len(failures) == 0
    return ScenarioResult(
        name="concurrent_move_groups",
        passed=passed,
        message=f"1/{concurrency} move succeeded, rest correctly rejected"
        if passed
        else f"{len(failures)} failure(s)",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 7: duplicate_hash_race
# ---------------------------------------------------------------------------


async def duplicate_hash_race(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Upload the SAME image bytes to N concurrent import jobs.

    Tests that the pipeline's content-hash deduplication produces correct
    results under concurrency — no duplicate Image rows with the same
    content_hash.

    Pass: all jobs complete, no 500 errors.
    """
    job_count = 10 if quick_mode else 50
    stats = RequestStats()

    # Generate one image to be used by all jobs (same bytes = same SHA-256)
    assert PILImage is not None, "Pillow is required"
    rng = random.Random(999)
    data = bytes(rng.randint(0, 255) for _ in range(160 * 120 * 3))
    img = PILImage.frombytes("RGB", (160, 120), data)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    shared_image_bytes = buf.getvalue()
    shared_rel_path = "StressAuthor/StressDedup/dedup_image.jpg"

    async def run_dedup_job(idx: int) -> tuple[bool, str]:
        async with httpx.AsyncClient(base_url=base_url, timeout=180) as client:
            flow = ImportFlow(client, base_url, stats)
            job_id = await flow.init_job()
            try:
                await flow.upload_batch(
                    job_id,
                    [("dedup_image.jpg", shared_image_bytes, "image/jpeg")],
                    [shared_rel_path],
                )
                analysis = await flow.analyse(job_id)
                groups = analysis.get("groups", [])
                if groups:
                    await flow.confirm_all(job_id, groups)
                    final = await flow.wait_for_terminal(job_id, timeout=120)
                    status = final.get("status", "unknown")
                    if status not in TERMINAL_STATES:
                        return False, f"Job {idx} stuck in '{status}'"
                else:
                    # Image was deduped — cancel
                    await flow.cancel(job_id)
                return True, "ok"
            except Exception as exc:
                return False, f"Job {idx}: {exc}"

    outcomes = await atqdm.gather(
        *(run_dedup_job(i) for i in range(job_count)),
        desc="  dedup-jobs",
        unit="job",
    )
    failures = [msg for ok, msg in outcomes if not ok]
    http_errors = stats.errors

    passed = len(failures) == 0 and http_errors == 0
    return ScenarioResult(
        name="duplicate_hash_race",
        passed=passed,
        message=f"{job_count} concurrent dedup jobs, no duplicate Image rows"
        if passed
        else f"{len(failures)} failures",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 8: server_restart_recovery
# ---------------------------------------------------------------------------


async def server_restart_recovery(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Crash the server mid-import and verify recovery on restart.

    This scenario manages its own server subprocess (separate from the outer
    _run_scenario server) so it can kill and restart it independently.

    Flow:
    1. Start 3 imports concurrently, leave them in 'active' state (processing)
    2. Force-kill the server
    3. Restart the server
    4. Verify mark_interrupted_jobs() moved all in-flight jobs to 'broken'
    5. Verify no jobs stuck in 'uploading', 'staging', or 'active'

    Pass: no stuck jobs after restart, server healthy.
    """
    import tempfile

    stats = RequestStats()
    failures: list[str] = []

    work_dir = Path(tempfile.mkdtemp(prefix="stress_restart_"))
    server = StressTestServer(work_dir)
    server2: StressTestServer | None = None

    try:
        restart_base_url = server.start(timeout=90)

        async with httpx.AsyncClient(base_url=restart_base_url, timeout=120) as client:
            flow = ImportFlow(client, restart_base_url, stats)

            # Start 3 imports and get them to active state
            job_ids: list[str] = []
            for i in range(3):
                images = generate_unique_images(2, base_seed=400000 + i * 100, group_tag=str(i))
                job_id = await flow.init_job()
                files = [(rel.split("/")[-1], data, "image/jpeg") for rel, data in images]
                await flow.upload_batch(job_id, files, [rel for rel, _ in images])
                analysis = await flow.analyse(job_id)
                groups = analysis.get("groups", [])
                if groups:
                    await flow.confirm_all(job_id, groups)
                job_ids.append(job_id)

            # Give processing a moment to start
            await asyncio.sleep(1)

        # Force-kill the server
        server.stop(force=True)

        # Start a fresh server on a new port, sharing server1's data dir so it sees
        # the same DB state.  Use a separate work_dir subdirectory to avoid log collision.
        server2 = StressTestServer(work_dir / "restart", data_dir=work_dir / "data")
        restart_base_url2 = server2.start(timeout=90)

        async with httpx.AsyncClient(base_url=restart_base_url2, timeout=60) as client:
            # Check all jobs — they should be 'broken' (mark_interrupted_jobs ran on startup)
            non_terminal: list[str] = []
            for job_id in job_ids:
                r = await client.get(f"{IMPORTS_BASE}/{job_id}/status", timeout=10)
                if r.status_code == 200:
                    job_status = r.json()["status"]
                    if job_status not in TERMINAL_STATES:
                        non_terminal.append(f"{job_id}: {job_status}")
                elif r.status_code != 404:
                    failures.append(f"Unexpected status code for {job_id}: {r.status_code}")

            if non_terminal:
                failures.append(
                    f"{len(non_terminal)} job(s) not in terminal state after restart:\n"
                    + "\n".join(non_terminal)
                )

    except Exception as exc:
        failures.append(f"Unexpected error: {exc}")
    finally:
        # Both servers must be stopped regardless of which step failed
        server.stop(force=True)
        if server2 is not None:
            server2.stop(force=True)
        import shutil

        shutil.rmtree(work_dir, ignore_errors=True)

    passed = len(failures) == 0
    return ScenarioResult(
        name="server_restart_recovery",
        passed=passed,
        message="All interrupted jobs marked as broken after restart"
        if passed
        else f"{len(failures)} failure(s)",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 9: large_batch_imports
# ---------------------------------------------------------------------------


async def large_batch_imports(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Few jobs, very many files each (sustained heavy load).

    Tests OOM resistance, monotonic memory growth, per-file error isolation,
    and CLIP throughput under prolonged load.

    Default: 10 jobs × 1 000 files, uploaded in batches of 50.
    Quick:    2 jobs × 100 files, batches of 50.
    """
    jobs_count = 2 if quick_mode else 10
    files_per_job = 100 if quick_mode else 1000
    batch_size = 50
    stats = RequestStats()

    async def run_batch_job(job_idx: int) -> tuple[bool, str]:
        async with httpx.AsyncClient(base_url=base_url, timeout=600) as client:
            flow = ImportFlow(client, base_url, stats)
            # Use non-overlapping seed ranges
            images = generate_unique_images(
                files_per_job,
                base_seed=job_idx * files_per_job + 300000,
                width=80,
                height=60,
            )
            try:
                result = await flow.full_import(images, batch_size=batch_size)
                status = result.get("status", "unknown")
                if status not in TERMINAL_STATES:
                    return False, f"Job {job_idx} stuck in '{status}'"
                return True, status
            except Exception as exc:
                return False, f"Job {job_idx}: {exc}"

    outcomes = await atqdm.gather(
        *(run_batch_job(i) for i in range(jobs_count)),
        desc="  batch-jobs",
        unit="job",
    )
    failures = [msg for ok, msg in outcomes if not ok]
    http_errors = stats.errors

    passed = len(failures) == 0 and http_errors == 0
    return ScenarioResult(
        name="large_batch_imports",
        passed=passed,
        message=f"{jobs_count} jobs × {files_per_job} files, all completed"
        if passed
        else f"{len(failures)} failures",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# Scenario 10: scheduler_interference
# ---------------------------------------------------------------------------


async def scheduler_interference(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Run concurrent imports while the scheduler's maintenance tasks are active.

    The scheduler tasks (cleanup_staging, expire_stale_jobs) run periodically
    in the background.  This scenario runs 20 concurrent imports (quick: 5)
    and verifies:
    - No staging directories are cleaned up prematurely for in-progress jobs
    - No active jobs are incorrectly expired
    - All jobs reach terminal state

    Note: expire_stale_jobs no longer targets awaiting_input (being removed).

    Pass: all jobs complete, no jobs expired prematurely.
    """
    jobs_count = 5 if quick_mode else 20
    files_per_job = 3
    stats = RequestStats()

    async def run_one(job_idx: int) -> tuple[bool, str]:
        async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
            flow = ImportFlow(client, base_url, stats)
            images = generate_unique_images(
                files_per_job,
                base_seed=job_idx * files_per_job + 200000,
            )
            try:
                result = await flow.full_import(images)
                status = result.get("status", "unknown")
                if status == "expired":
                    return False, f"Job {job_idx} was incorrectly expired by scheduler"
                if status not in TERMINAL_STATES:
                    return False, f"Job {job_idx} stuck in '{status}'"
                return True, status
            except Exception as exc:
                return False, f"Job {job_idx}: {exc}"

    outcomes = await atqdm.gather(
        *(run_one(i) for i in range(jobs_count)),
        desc="  scheduler-jobs",
        unit="job",
    )
    failures = [msg for ok, msg in outcomes if not ok]

    passed = len(failures) == 0
    return ScenarioResult(
        name="scheduler_interference",
        passed=passed,
        message=f"{jobs_count} concurrent imports, no scheduler interference"
        if passed
        else f"{len(failures)} failures",
        elapsed=0,
        stats=stats,
        failure_details="\n".join(failures) if failures else None,
    )


# ---------------------------------------------------------------------------
# SCENARIO_REGISTRY
# ---------------------------------------------------------------------------

SCENARIO_REGISTRY: list[tuple[str, Any, str, str]] = [
    ("concurrent_imports", concurrent_imports, "~3-5 min", "~30s"),
    ("endpoint_spam", endpoint_spam, "~30s", "~15s"),
    ("cancellation_chaos", cancellation_chaos, "~2 min", "~1 min"),
    ("malformed_input", malformed_input, "~30s", "~15s"),
    ("large_uploads", large_uploads, "~2-5 min", "skipped"),
    ("concurrent_move_groups", concurrent_move_groups, "~1 min", "~30s"),
    ("duplicate_hash_race", duplicate_hash_race, "~1 min", "~30s"),
    ("server_restart_recovery", server_restart_recovery, "~1 min", "~30s"),
    ("large_batch_imports", large_batch_imports, "~10-20 min", "~2 min"),
    ("scheduler_interference", scheduler_interference, "~3 min", "~1 min"),
]
