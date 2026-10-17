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

The scenarios drive the imports API described in design/ingestion.md (ADR-018):
create job → manifest → (archives) → seal → (client hashes) → per-file PUT, then
poll ``GET /imports/{id}``. A job's status is derived from its items: ``active``,
``paused``, ``completed`` or ``cancelled``. Jobs never fail; outcomes are item
counts (done / duplicate / failed / skipped).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import random
import shutil
import tempfile
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

# Job states in which nothing more will happen without user action.
TERMINAL_STATES = frozenset({"completed", "cancelled"})
# Server-side chunk limits (MAX_MANIFEST_CHUNK / MAX_HASH_CHUNK in import_schemas.py).
MANIFEST_CHUNK = 2000
HASH_CHUNK = 2000
# Concurrent PUTs per job; the frontend uses 3.
UPLOAD_CONCURRENCY = 4

Images = list[tuple[str, bytes]]


# ---------------------------------------------------------------------------
# ImportFlow — thin async wrapper around the imports HTTP API
# ---------------------------------------------------------------------------


class ImportFlow:
    """Wraps the imports API for use within async stress scenarios.

    Every request is recorded in ``stats``; a response >= 500 counts as an error.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        stats: RequestStats | None = None,
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._stats = stats or RequestStats()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        content: bytes | None = None,
        params: dict | None = None,
        timeout: float = 60.0,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/octet-stream"} if content is not None else None
        t0 = time.monotonic()
        r = await self._client.request(
            method,
            self._base + path,
            json=json,
            content=content,
            params=params,
            headers=headers,
            timeout=timeout,
        )
        self._stats.record(time.monotonic() - t0, ok=r.status_code < 500)
        return r

    async def create(self, label: str = "stress", image_type: str = "battlemap") -> str:
        """POST /imports → job id."""
        r = await self.request(
            "POST", IMPORTS_BASE, json={"label": label, "default_image_type": image_type}
        )
        r.raise_for_status()
        return r.json()["id"]

    async def manifest(self, job_id: str, images: Images) -> dict[str, dict]:
        """POST /imports/{id}/manifest in chunks. Returns manifest items by relative path."""
        by_path: dict[str, dict] = {}
        for start in range(0, len(images), MANIFEST_CHUNK):
            chunk = images[start : start + MANIFEST_CHUNK]
            files = [
                {"client_ref": rel, "relative_path": rel, "size": len(data)} for rel, data in chunk
            ]
            r = await self.request(
                "POST", f"{IMPORTS_BASE}/{job_id}/manifest", json={"files": files}, timeout=120
            )
            r.raise_for_status()
            for item in r.json()["items"]:
                by_path[item["client_ref"]] = item
        return by_path

    async def seal(self, job_id: str) -> dict:
        """POST /imports/{id}/seal → job detail (idempotent)."""
        r = await self.request("POST", f"{IMPORTS_BASE}/{job_id}/seal", timeout=300)
        r.raise_for_status()
        return r.json()

    async def submit_hashes(self, job_id: str, hashes: dict[int, str]) -> dict[int, str]:
        """POST /imports/{id}/hashes → new state per item id."""
        states: dict[int, str] = {}
        entries = [{"item_id": i, "sha256": h} for i, h in hashes.items()]
        for start in range(0, len(entries), HASH_CHUNK):
            r = await self.request(
                "POST",
                f"{IMPORTS_BASE}/{job_id}/hashes",
                json={"items": entries[start : start + HASH_CHUNK]},
            )
            r.raise_for_status()
            states.update({e["item_id"]: e["state"] for e in r.json()["items"]})
        return states

    async def put_content(
        self, job_id: str, item_id: int, data: bytes, timeout: float = 120.0
    ) -> httpx.Response:
        """PUT /imports/{id}/items/{item_id}/content (raw body). Caller checks the status."""
        return await self.request(
            "PUT", f"{IMPORTS_BASE}/{job_id}/items/{item_id}/content", content=data, timeout=timeout
        )

    async def upload_archive(
        self, job_id: str, name: str, data: bytes, timeout: float = 300.0
    ) -> httpx.Response:
        """PUT /imports/{id}/archives?name=… (raw zip body). Caller checks the status."""
        return await self.request(
            "PUT",
            f"{IMPORTS_BASE}/{job_id}/archives",
            content=data,
            params={"name": name},
            timeout=timeout,
        )

    async def cancel(self, job_id: str) -> httpx.Response:
        """POST /imports/{id}/cancel."""
        return await self.request("POST", f"{IMPORTS_BASE}/{job_id}/cancel")

    async def get_job(self, job_id: str) -> dict:
        """GET /imports/{id} → job detail with counts and groups."""
        r = await self.request("GET", f"{IMPORTS_BASE}/{job_id}")
        r.raise_for_status()
        return r.json()

    async def wait_for_terminal(self, job_id: str, timeout: float = 300.0) -> dict:
        """Poll until the job is completed or cancelled. Raises RuntimeError on timeout."""
        deadline = time.monotonic() + timeout
        detail: dict = {}
        while time.monotonic() < deadline:
            detail = await self.get_job(job_id)
            if detail["status"] in TERMINAL_STATES:
                return detail
            await asyncio.sleep(0.5)
        raise RuntimeError(
            f"Job {job_id} did not reach a terminal state within {timeout}s "
            f"(status={detail.get('status')}, counts={detail.get('counts')})"
        )

    async def upload_all(
        self, job_id: str, items: dict[str, dict], images: Images, concurrency: int
    ) -> None:
        """PUT the bytes of every item still awaiting them, ``concurrency`` at a time."""
        sem = asyncio.Semaphore(concurrency)
        data_by_path = dict(images)

        async def one(rel: str, item: dict) -> None:
            if item["state"] != "awaiting_bytes":
                return
            async with sem:
                r = await self.put_content(job_id, item["item_id"], data_by_path[rel])
                r.raise_for_status()

        await asyncio.gather(*(one(rel, item) for rel, item in items.items()))

    async def start_import(
        self,
        images: Images,
        image_type: str = "battlemap",
        *,
        send_hashes: bool = False,
        concurrency: int = UPLOAD_CONCURRENCY,
    ) -> str:
        """Create → manifest → seal → (hashes) → upload. Returns the job id without waiting."""
        job_id = await self.create(image_type=image_type)
        items = await self.manifest(job_id, images)
        await self.seal(job_id)
        if send_hashes:
            data_by_path = dict(images)
            hashes = {
                item["item_id"]: hashlib.sha256(data_by_path[rel]).hexdigest()
                for rel, item in items.items()
                if item["state"] == "awaiting_bytes"
            }
            states = await self.submit_hashes(job_id, hashes)
            for item in items.values():
                item["state"] = states.get(item["item_id"], item["state"])
        await self.upload_all(job_id, items, images, concurrency)
        return job_id

    async def full_import(
        self,
        images: Images,
        image_type: str = "battlemap",
        *,
        send_hashes: bool = False,
        concurrency: int = UPLOAD_CONCURRENCY,
        timeout: float = 300.0,
    ) -> dict:
        """Run the complete flow and poll until terminal. Returns the final job detail."""
        job_id = await self.start_import(
            images, image_type, send_hashes=send_hashes, concurrency=concurrency
        )
        return await self.wait_for_terminal(job_id, timeout=timeout)


def check_complete(detail: dict, label: str) -> str | None:
    """Return a failure message unless every item of a finished job was imported or deduped."""
    counts = detail["counts"]
    if detail["status"] != "completed":
        return f"{label}: status {detail['status']} (counts {counts})"
    if (
        counts["failed"]
        or counts["skipped"]
        or counts["done"] + counts["duplicate"] != counts["total"]
    ):
        return f"{label}: unexpected outcome {counts}"
    return None


# ---------------------------------------------------------------------------
# generate_unique_images — deterministic per-job image sets
# ---------------------------------------------------------------------------


def generate_unique_images(
    count: int,
    base_seed: int,
    group_tag: str = "0",
    width: int = 160,
    height: int = 120,
) -> Images:
    """Return `count` unique (relative_path, bytes_data) JPEG tuples.

    Each image has a unique seed so its bytes and pixels differ from all others,
    so dedup never collapses them. Use non-overlapping base_seed values across
    concurrent jobs.

    Relative paths use the convention ``StressAuthor/StressMap_{group_tag}/image_{i}.jpg``
    so the grouping logic bundles them into one group per job.
    """
    images: Images = []
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


def _result(
    name: str, failures: list[str], ok_message: str, stats: RequestStats | None = None
) -> ScenarioResult:
    if stats is not None and stats.errors:
        failures = [*failures, f"{stats.errors} HTTP 5xx response(s)"]
    return ScenarioResult(
        name=name,
        passed=not failures,
        message=ok_message if not failures else f"{len(failures)} failure(s)",
        elapsed=0,  # set by _run_scenario
        stats=stats,
        failure_details="\n".join(failures[:20]) if failures else None,
    )


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
    """Many concurrent jobs, each running the full import flow.

    Tests SQLite write-lock contention between the API and the ingest worker,
    round-robin claiming across jobs, and the LanceDB write path.

    Pass: every job completes with all its files imported, zero 5xx responses.
    """
    jobs_count = 10 if quick_mode else 100
    files_per_job = 3 if quick_mode else 5
    stats = RequestStats()

    async def run_one_job(job_idx: int) -> str | None:
        async with httpx.AsyncClient(timeout=300) as client:
            flow = ImportFlow(client, base_url, stats)
            images = generate_unique_images(
                files_per_job, base_seed=job_idx * files_per_job, group_tag=str(job_idx)
            )
            try:
                return check_complete(await flow.full_import(images), f"Job {job_idx}")
            except Exception as exc:
                return f"Job {job_idx} raised {type(exc).__name__}: {exc}"

    outcomes = await atqdm.gather(
        *(run_one_job(i) for i in range(jobs_count)), desc="  jobs", unit="job"
    )
    failures = [msg for msg in outcomes if msg]
    return _result(
        "concurrent_imports", failures, f"{jobs_count}/{jobs_count} jobs completed", stats
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
    1. N concurrent cancels of one sealed job → all 200, job ends cancelled
    2. N concurrent detail polls → all 200, consistent status
    3. N concurrent PUTs to a cancelled job's item → all 409
    4. N concurrent seals of one job → all 200, identical group plan
    5. N concurrent PUTs of the same item → all 200, exactly one image imported

    Pass: no 5xx responses, idempotent endpoints stay idempotent.
    """
    concurrency = 20 if quick_mode else 100
    stats = RequestStats()
    failures: list[str] = []

    with tqdm(total=5, desc="  sub-tests", unit="sub-test", leave=True) as pbar:
        async with httpx.AsyncClient(timeout=60) as client:
            flow = ImportFlow(client, base_url, stats)

            # --- 1: concurrent cancels ---
            pbar.set_postfix_str("concurrent-cancels")
            images = generate_unique_images(1, base_seed=900000)
            job_id = await flow.create()
            items = await flow.manifest(job_id, images)
            await flow.seal(job_id)
            responses = await asyncio.gather(*(flow.cancel(job_id) for _ in range(concurrency)))
            codes = {r.status_code for r in responses}
            if codes != {200}:
                failures.append(f"1: expected only 200 from cancel, got {codes}")
            if (await flow.get_job(job_id))["status"] != "cancelled":
                failures.append("1: job not cancelled after concurrent cancels")
            pbar.update(1)

            # --- 2: concurrent detail polls ---
            pbar.set_postfix_str("concurrent-polls")
            job_id2 = await flow.create()

            async def poll() -> tuple[int, str]:
                r = await flow.request("GET", f"{IMPORTS_BASE}/{job_id2}", timeout=30)
                return r.status_code, r.json().get("status", "") if r.status_code == 200 else ""

            polls = await asyncio.gather(*(poll() for _ in range(concurrency)))
            if {c for c, _ in polls} != {200}:
                failures.append(f"2: poll status codes { ({c for c, _ in polls}) }")
            if len({s for _, s in polls}) > 1:
                failures.append(f"2: inconsistent status values { ({s for _, s in polls}) }")
            await flow.cancel(job_id2)
            pbar.update(1)

            # --- 3: uploads to a cancelled job (its item is now skipped) ---
            pbar.set_postfix_str("upload-to-cancelled")
            (item,) = items.values()
            data = images[0][1]
            responses = await asyncio.gather(
                *(flow.put_content(job_id, item["item_id"], data) for _ in range(concurrency))
            )
            codes = {r.status_code for r in responses}
            if codes != {409}:
                failures.append(f"3: expected only 409 for upload to cancelled job, got {codes}")
            pbar.update(1)

            # --- 4: concurrent seals ---
            pbar.set_postfix_str("concurrent-seals")
            images4 = generate_unique_images(2, base_seed=700000, group_tag="seal")
            job_id4 = await flow.create()
            items4 = await flow.manifest(job_id4, images4)
            responses = await asyncio.gather(
                *(
                    flow.request("POST", f"{IMPORTS_BASE}/{job_id4}/seal", timeout=120)
                    for _ in range(concurrency)
                )
            )
            codes = {r.status_code for r in responses}
            if codes != {200}:
                failures.append(f"4: expected only 200 from seal, got {codes}")
            plans = {
                tuple(sorted(g["id"] for g in r.json()["groups"]))
                for r in responses
                if r.status_code == 200
            }
            if len(plans) != 1 or len(next(iter(plans), ())) != 1:
                failures.append(f"4: concurrent seals produced differing group plans: {plans}")
            pbar.update(1)

            # --- 5: concurrent PUTs of the same item ---
            pbar.set_postfix_str("concurrent-same-put")
            rel, data5 = images4[0]
            responses = await asyncio.gather(
                *(
                    flow.put_content(job_id4, items4[rel]["item_id"], data5)
                    for _ in range(concurrency)
                )
            )
            codes = {r.status_code for r in responses}
            if codes != {200}:
                failures.append(f"5: expected only 200 from repeated PUT, got {codes}")
            await flow.upload_all(job_id4, {images4[1][0]: items4[images4[1][0]]}, images4, 1)
            try:
                detail = await flow.wait_for_terminal(job_id4, timeout=120)
                if msg := check_complete(detail, "5"):
                    failures.append(msg)
                elif detail["counts"]["done"] != 2:
                    failures.append(f"5: expected 2 images imported, got {detail['counts']}")
            except RuntimeError as exc:
                failures.append(f"5: {exc}")
            pbar.update(1)

    return _result(
        "endpoint_spam", failures, f"{concurrency * 5} requests across 5 sub-tests", stats
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
    """Cancel at every stage of an import and check the resulting states.

    (a) Before seal (manifest only)              → cancelled, items skipped
    (b) After seal, before any bytes              → cancelled, items skipped
    (c) Right after uploading (while processing)  → cancelled; nothing left processing,
        finished items kept
    (d) After completion                          → 200, job stays completed, images kept

    Pass: correct codes and states, no 5xx.
    """
    stats = RequestStats()
    failures: list[str] = []
    stages = ["(a) before-seal", "(b) after-seal", "(c) processing", "(d) completed"]

    async def cancel_ok(flow: ImportFlow, job_id: str, label: str) -> dict:
        r = await flow.cancel(job_id)
        if r.status_code != 200:
            failures.append(f"{label}: cancel returned {r.status_code}")
        return await flow.get_job(job_id)

    async with httpx.AsyncClient(timeout=120) as client:
        flow = ImportFlow(client, base_url, stats)

        with tqdm(total=len(stages), desc="  stages", unit="stage") as pbar:
            # (a) before seal
            pbar.set_postfix_str(stages[0])
            job_a = await flow.create()
            await flow.manifest(job_a, generate_unique_images(2, base_seed=500000, group_tag="a"))
            detail = await cancel_ok(flow, job_a, "(a)")
            if detail["status"] != "cancelled" or detail["counts"]["skipped"] != 2:
                failures.append(f"(a) unexpected state {detail['status']} {detail['counts']}")
            pbar.update(1)

            # (b) after seal, before bytes
            pbar.set_postfix_str(stages[1])
            job_b = await flow.create()
            await flow.manifest(job_b, generate_unique_images(2, base_seed=510000, group_tag="b"))
            await flow.seal(job_b)
            detail = await cancel_ok(flow, job_b, "(b)")
            if detail["status"] != "cancelled" or detail["counts"]["skipped"] != 2:
                failures.append(f"(b) unexpected state {detail['status']} {detail['counts']}")
            pbar.update(1)

            # (c) while processing
            pbar.set_postfix_str(stages[2])
            job_c = await flow.start_import(
                generate_unique_images(6, base_seed=520000, group_tag="c")
            )
            await cancel_ok(flow, job_c, "(c)")
            # An in-flight batch finishes and is kept; wait for it to drain.
            deadline = time.monotonic() + 60
            while True:
                detail = await flow.get_job(job_c)
                counts = detail["counts"]
                if counts["processing"] == 0 or time.monotonic() > deadline:
                    break
                await asyncio.sleep(0.5)
            if detail["status"] != "cancelled":
                failures.append(f"(c) status {detail['status']} after cancel")
            if counts["processing"] or counts["ready"] or counts["awaiting_bytes"]:
                failures.append(f"(c) open items left after cancel: {counts}")
            pbar.update(1)

            # (d) after completion
            pbar.set_postfix_str(stages[3])
            done = await flow.full_import(
                generate_unique_images(1, base_seed=530000, group_tag="d")
            )
            if msg := check_complete(done, "(d) setup"):
                failures.append(msg)
            detail = await cancel_ok(flow, done["id"], "(d)")
            if (
                detail["status"] != "completed"
                or detail["counts"]["done"] != done["counts"]["done"]
            ):
                failures.append(
                    f"(d) cancel changed a completed job: {detail['status']} {detail['counts']}"
                )
            pbar.update(1)

    return _result(
        "cancellation_chaos", failures, "All 4 cancellation stages handled correctly", stats
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
    """Upload malformed/corrupt files and check they fail cleanly.

    Each fixture has a valid magic-byte header and a corrupt body. Corrupt images
    are rejected by the upload-time content check; corrupt videos pass it and must
    fail in the worker. Each goes into a fresh job: images and videos via
    manifest + PUT, zips via the archive route.

    Pass: no 5xx, no hangs, every job completes, and no corrupt file is imported.
    """
    malformed_mb = 500 if large_mode else 5
    _p = fixtures_dir / f"malformed_{malformed_mb}mb"
    test_files = [
        ("malformed_jpeg", Path(f"{_p}.jpg")),
        ("malformed_png", Path(f"{_p}.png")),
        ("malformed_webp", Path(f"{_p}.webp")),
        ("malformed_mp4", Path(f"{_p}.mp4")),
        ("malformed_webm", Path(f"{_p}.webm")),
        ("malformed_zip", Path(f"{_p}.zip")),
        ("near_zip_bomb", fixtures_dir / "near_bomb.zip"),
    ]

    stats = RequestStats()
    failures: list[str] = []
    tested = 0

    async with httpx.AsyncClient(timeout=60) as client:
        flow = ImportFlow(client, base_url, stats)

        for label, path in test_files:
            if not path.exists():
                continue  # e.g. video fixtures without ffmpeg
            tested += 1
            data = path.read_bytes()
            job_id = await flow.create(label=label)
            try:
                if path.suffix == ".zip":
                    r = await flow.upload_archive(job_id, path.name, data, timeout=60)
                    if r.status_code >= 400:
                        failures.append(f"{label}: archive upload returned {r.status_code}")
                        continue
                    await flow.seal(job_id)
                else:
                    images = [(f"Stress/Malformed/{path.name}", data)]
                    items = await flow.manifest(job_id, images)
                    await flow.seal(job_id)
                    (item,) = items.values()
                    if item["state"] == "awaiting_bytes":
                        r = await flow.put_content(job_id, item["item_id"], data, timeout=60)
                        if r.status_code >= 400 and r.status_code != 413:
                            failures.append(f"{label}: upload returned {r.status_code}")
                detail = await flow.wait_for_terminal(job_id, timeout=120)
                if detail["counts"]["done"]:
                    failures.append(f"{label}: corrupt file was imported ({detail['counts']})")
            except httpx.TimeoutException:
                failures.append(f"{label}: request timed out")
            except (httpx.HTTPStatusError, RuntimeError) as exc:
                failures.append(f"{label}: {exc}")
            finally:
                await flow.cancel(job_id)

    return _result(
        "malformed_input", failures, f"{tested} malformed fixtures tested, all rejected", stats
    )


# ---------------------------------------------------------------------------
# Scenario 5: large_uploads
# ---------------------------------------------------------------------------


async def _upload_one_file(flow: ImportFlow, path: Path, data: bytes) -> str | None:
    """Put one large file into a fresh job and cancel it. Returns a failure message or None."""
    job_id = await flow.create(label=path.name)
    try:
        if path.suffix == ".zip":
            r = await flow.upload_archive(job_id, path.name, data)
        else:
            items = await flow.manifest(job_id, [(f"Stress/Large/{path.name}", data)])
            await flow.seal(job_id)
            (item,) = items.values()
            if item["state"] != "awaiting_bytes":
                return None  # rejected at manifest time (e.g. over the size limit)
            r = await flow.put_content(job_id, item["item_id"], data, timeout=300)
        if r.status_code >= 500:
            return f"{path.name}: got {r.status_code}"
        return None
    except Exception as exc:
        return f"{path.name} {type(exc).__name__}: {exc}"
    finally:
        await flow.cancel(job_id)


async def large_uploads(
    *,
    base_url: str,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
) -> ScenarioResult:
    """Upload large video and ZIP files — sequentially, then 5 at once.

    Skipped in --quick mode unless --large is given.

    Pass: no OOM, no 5xx; uploads complete or are rejected cleanly.
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

    malformed_mb = 500 if large_mode else 5
    candidates = [
        fixtures_dir / f"malformed_{malformed_mb}mb.mp4",
        fixtures_dir / f"malformed_{malformed_mb}mb.webm",
        fixtures_dir / f"large_{1000 if large_mode else 100}.zip",
    ]
    available = [p for p in candidates if p.exists()]
    if not available:
        return ScenarioResult(
            name="large_uploads",
            passed=True,
            message="No large fixtures available — run generate-fixtures first",
            elapsed=0,
        )

    async with httpx.AsyncClient(timeout=600) as client:
        flow = ImportFlow(client, base_url, stats)
        cache = {p: p.read_bytes() for p in available}

        for path in available:
            if msg := await _upload_one_file(flow, path, cache[path]):
                failures.append(f"Sequential {msg}")

        big = available[0]
        outcomes = await asyncio.gather(
            *(_upload_one_file(flow, big, cache[big]) for _ in range(5))
        )
        failures.extend(f"Concurrent {msg}" for msg in outcomes if msg)

    return _result(
        "large_uploads", failures, f"Tested: {', '.join(p.name for p in available)}", stats
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

    Imports images into two groups (source and target), then fires 20 concurrent
    move-images requests for the same images. Exactly one should succeed; the
    rest get 400/404.

    Pass: exactly one move succeeds, no 5xx, every image ends up in the target.
    """
    concurrency = 20
    stats = RequestStats()
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=300) as client:
        flow = ImportFlow(client, base_url, stats)

        group_ids: list[int] = []
        for tag, seed, count in (("src", 600000, 4), ("tgt", 600100, 2)):
            detail = await flow.full_import(
                generate_unique_images(count, base_seed=seed, group_tag=tag)
            )
            if msg := check_complete(detail, f"{tag} import"):
                return _result("concurrent_move_groups", [msg], "", stats)
            ids = [g["image_group_id"] for g in detail["groups"] if g["image_group_id"]]
            if not ids:
                return _result(
                    "concurrent_move_groups", [f"{tag} import has no gallery group"], "", stats
                )
            group_ids.append(ids[0])
        src_group_id, tgt_group_id = group_ids

        r = await client.get(f"{base_url}{GROUPS_BASE}/{src_group_id}", timeout=30)
        if r.status_code != 200:
            return _result(
                "concurrent_move_groups", [f"Could not fetch source group: {r.status_code}"], ""
            )
        image_ids = [img["id"] for img in r.json().get("images", [])]
        if not image_ids:
            return _result("concurrent_move_groups", ["Source group has no images"], "")

        async def do_move() -> int:
            r2 = await flow.request(
                "POST",
                f"{GROUPS_BASE}/{src_group_id}/move-images",
                json={"target_group_id": tgt_group_id, "image_ids": image_ids},
                timeout=30,
            )
            return r2.status_code

        move_codes = await asyncio.gather(*(do_move() for _ in range(concurrency)))
        ok_moves = sum(1 for c in move_codes if c == 200)
        if ok_moves != 1:
            failures.append(
                f"Expected exactly 1 successful move, got {ok_moves} ({sorted(move_codes)})"
            )
        bad_codes = {c for c in move_codes if c not in (200, 400, 404, 409)}
        if bad_codes:
            failures.append(f"Unexpected move status codes: {bad_codes}")

        r3 = await client.get(f"{base_url}{GROUPS_BASE}/{src_group_id}", timeout=30)
        if r3.status_code == 200 and any(
            img["id"] in set(image_ids) for img in r3.json().get("images", [])
        ):
            failures.append("Some moved images are still in the source group")
        r4 = await client.get(f"{base_url}{GROUPS_BASE}/{tgt_group_id}", timeout=30)
        if r4.status_code == 200:
            tgt_imgs = {img["id"] for img in r4.json().get("images", [])}
            missing = [iid for iid in image_ids if iid not in tgt_imgs]
            if missing:
                failures.append(f"Images not found in target group: {missing}")

    return _result(
        "concurrent_move_groups",
        failures,
        f"1/{concurrency} move succeeded, rest correctly rejected",
        stats,
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
    """Import the SAME image bytes in N concurrent jobs.

    Half the jobs also send the client-side SHA-256 (``POST /hashes``) before
    uploading, so both dedup paths (client hint and commit-time check) race.

    Pass: every job completes, exactly one copy is imported across all jobs
    (the rest are ``duplicate``), no 5xx.
    """
    job_count = 10 if quick_mode else 50
    stats = RequestStats()

    assert PILImage is not None, "Pillow is required"
    rng = random.Random(999)
    pixels = bytes(rng.randint(0, 255) for _ in range(160 * 120 * 3))
    buf = io.BytesIO()
    PILImage.frombytes("RGB", (160, 120), pixels).save(buf, format="JPEG", quality=85)
    images = [("StressAuthor/StressDedup/dedup_image.jpg", buf.getvalue())]

    async def run_dedup_job(idx: int) -> dict | str:
        async with httpx.AsyncClient(timeout=180) as client:
            flow = ImportFlow(client, base_url, stats)
            try:
                return await flow.full_import(images, send_hashes=idx % 2 == 0, timeout=120)
            except Exception as exc:
                return f"Job {idx} {type(exc).__name__}: {exc}"

    outcomes = await atqdm.gather(
        *(run_dedup_job(i) for i in range(job_count)), desc="  dedup-jobs", unit="job"
    )
    failures = [o for o in outcomes if isinstance(o, str)]
    details = [o for o in outcomes if isinstance(o, dict)]
    failures += [msg for i, d in enumerate(details) if (msg := check_complete(d, f"Job {i}"))]
    imported = sum(d["counts"]["done"] for d in details)
    if not failures and imported != 1:
        failures.append(f"Expected exactly 1 imported copy across {job_count} jobs, got {imported}")

    return _result(
        "duplicate_hash_race",
        failures,
        f"{job_count} concurrent jobs, 1 imported, {job_count - 1} deduplicated",
        stats,
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
    """Kill the server mid-import and check the imports finish after a restart.

    Manages its own server subprocesses (separate from the outer _run_scenario
    server) so it can kill and restart them on the same storage.

    1. Start 3 imports and upload all their bytes
    2. SIGKILL the server while the worker is processing
    3. Restart on the same storage; ``IngestWorker.recover()`` re-queues items
       left ``processing``
    4. Every job completes with all files imported, none stuck

    Pass: all jobs complete with every file done, no 5xx.
    """
    stats = RequestStats()
    failures: list[str] = []
    files_per_job = 8

    work_dir = Path(tempfile.mkdtemp(prefix="stress_restart_"))
    server = StressTestServer(work_dir)
    server2: StressTestServer | None = None

    try:
        url1 = server.start(timeout=90)
        server.wait_for_clip()
        async with httpx.AsyncClient(timeout=120) as client:
            flow = ImportFlow(client, url1, stats)
            job_ids = await asyncio.gather(
                *(
                    flow.start_import(
                        generate_unique_images(
                            files_per_job, base_seed=400000 + i * 100, group_tag=str(i)
                        )
                    )
                    for i in range(3)
                )
            )
            before = [(await flow.get_job(j))["counts"] for j in job_ids]

        server.stop(force=True)

        # Same storage root, new process (and port); separate work dir for its log.
        server2 = StressTestServer(work_dir / "restart", storage_dir=work_dir)
        url2 = server2.start(timeout=90)
        async with httpx.AsyncClient(timeout=60) as client:
            flow = ImportFlow(client, url2, stats)
            for job_id, counts_before in zip(job_ids, before, strict=True):
                try:
                    detail = await flow.wait_for_terminal(job_id, timeout=180)
                except RuntimeError as exc:
                    failures.append(f"{job_id} (before kill: {counts_before}): {exc}")
                    continue
                if msg := check_complete(detail, f"{job_id} (before kill: {counts_before})"):
                    failures.append(msg)
    except Exception as exc:
        failures.append(f"Unexpected error {type(exc).__name__}: {exc}")
    finally:
        server.stop(force=True)
        if server2 is not None:
            server2.stop(force=True)
        if failures:
            # Keep both servers' logs and the shared database for post-mortem.
            failures.append(f"Restart work dir kept: {work_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    return _result(
        "server_restart_recovery", failures, "All interrupted imports finished after restart", stats
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

    Tests memory growth, per-file error isolation and embedding throughput
    under prolonged load.

    Default: 10 jobs × 1 000 files. Quick: 2 jobs × 100 files.
    """
    jobs_count = 2 if quick_mode else 10
    files_per_job = 100 if quick_mode else 1000
    stats = RequestStats()

    async def run_batch_job(job_idx: int) -> str | None:
        async with httpx.AsyncClient(timeout=600) as client:
            flow = ImportFlow(client, base_url, stats)
            images = generate_unique_images(
                files_per_job,
                base_seed=job_idx * files_per_job + 300000,
                group_tag=f"batch{job_idx}",
                width=80,
                height=60,
            )
            try:
                detail = await flow.full_import(images, timeout=1800)
                return check_complete(detail, f"Job {job_idx}")
            except Exception as exc:
                return f"Job {job_idx} {type(exc).__name__}: {exc}"

    outcomes = await atqdm.gather(
        *(run_batch_job(i) for i in range(jobs_count)), desc="  batch-jobs", unit="job"
    )
    failures = [msg for msg in outcomes if msg]
    return _result(
        "large_batch_imports",
        failures,
        f"{jobs_count} jobs × {files_per_job} files, all completed",
        stats,
    )


# ---------------------------------------------------------------------------
# SCENARIO_REGISTRY
# ---------------------------------------------------------------------------

SCENARIO_REGISTRY: list[tuple[str, Any, str, str]] = [
    ("concurrent_imports", concurrent_imports, "~3-5 min", "~30s"),
    ("endpoint_spam", endpoint_spam, "~30s", "~15s"),
    ("cancellation_chaos", cancellation_chaos, "~1 min", "~1 min"),
    ("malformed_input", malformed_input, "~2 min", "~2 min"),
    ("large_uploads", large_uploads, "~2-5 min", "skipped"),
    ("concurrent_move_groups", concurrent_move_groups, "~1 min", "~30s"),
    ("duplicate_hash_race", duplicate_hash_race, "~1 min", "~30s"),
    ("server_restart_recovery", server_restart_recovery, "~1 min", "~1 min"),
    ("large_batch_imports", large_batch_imports, "~10-20 min", "~2 min"),
]
