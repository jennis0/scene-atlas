"""Stress scenarios for the ingest pipeline (ADR-018, design/ingestion.md).

Each scenario is ``async def scenario(ctx: ScenarioContext) -> ScenarioResult``
and gets a fresh server with its own data and library directories.

The client follows the real upload protocol (§7):

    create job → manifest chunks (≤2000) → optional archives → seal
      → POST /hashes → concurrent PUT /items/{id}/content (3–4 in flight)
      → poll GET /imports (ETag) until every job settles

These scenarios complement ``backend/tests/integration`` (which drive the worker
synchronously): here everything runs against a live server and worker thread,
concurrently, at volume, and some scenarios crash or restart the server.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from stress_tests.fixtures import FixturePaths, image_set, noise_jpeg, noise_png, zip_bytes
from stress_tests.run import RequestStats, ScenarioContext, ScenarioResult, StressTestServer

API = "/api/v1"
IMPORTS = f"{API}/imports"
GROUPS = f"{API}/groups"

MANIFEST_CHUNK = 2000
HASH_CHUNK = 2000
UPLOAD_CONCURRENCY = 4
BATCH_SIZE = 16  # ingestion_batch_size default: the most a pause/cancel lets finish
OPEN_STATES = ("awaiting_bytes", "ready", "processing")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Check:
    """Collects failed expectations; a scenario passes when none failed."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def __call__(self, ok: bool, message: str) -> bool:
        if not ok:
            self.failures.append(message)
        return ok

    def eq(self, actual: Any, expected: Any, what: str) -> bool:
        return self(actual == expected, f"{what}: expected {expected!r}, got {actual!r}")

    def note(self, message: str) -> None:
        self.notes.append(message)

    def result(self, name: str, stats: RequestStats, ok_message: str) -> ScenarioResult:
        passed = not self.failures
        message = ok_message if passed else f"{len(self.failures)} check(s) failed"
        if self.notes:
            message += " | " + "; ".join(self.notes)
        return ScenarioResult(
            name=name,
            passed=passed,
            message=message,
            elapsed=0,  # set by the runner
            stats=stats,
            failure_details="\n".join(self.failures) if self.failures else None,
        )


def done_at_least(n: int) -> Callable[[dict], bool]:
    return lambda job: job["counts"]["done"] >= n


def settled(job: dict) -> bool:
    """A job whose items can't change any more without a user action."""
    counts = job["counts"]
    if job["status"] == "completed":
        return True
    return job["status"] == "cancelled" and counts["processing"] == 0 and counts["ready"] == 0


def entries(files: list[tuple[str, bytes]]) -> list[dict]:
    return [
        {"client_ref": str(i), "relative_path": path, "size": len(data)}
        for i, (path, data) in enumerate(files)
    ]


@dataclass
class StartedImport:
    job_id: str
    manifest: list[dict]

    @property
    def item_ids(self) -> dict[str, int]:
        """relative_path → item_id"""
        return {m["relative_path"]: m["item_id"] for m in self.manifest}


@dataclass
class PollStats:
    polls: int = 0
    not_modified: int = 0


class ImportClient:
    """Async client for the imports API that records request timings and 5xx errors."""

    def __init__(self, client: httpx.AsyncClient, stats: RequestStats) -> None:
        self.http = client
        self.stats = stats
        self.poll = PollStats()
        self.bytes_sent = 0
        self.unexpected: list[str] = []  # 5xx and transport errors

    async def req(self, method: str, path: str, **kwargs) -> httpx.Response:
        t0 = time.monotonic()
        try:
            r = await self.http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            self.stats.record(time.monotonic() - t0, ok=False)
            self.unexpected.append(f"{method} {path}: {type(exc).__name__}: {exc}")
            raise
        self.stats.record(time.monotonic() - t0, ok=r.status_code < 500)
        if r.status_code >= 500:
            self.unexpected.append(f"{method} {path}: HTTP {r.status_code} {r.text[:300]}")
        return r

    async def ok(self, method: str, path: str, **kwargs) -> Any:
        r = await self.req(method, path, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json()

    async def create(self, label: str, image_type: str = "battlemap") -> str:
        body = {"label": label, "default_image_type": image_type}
        return (await self.ok("POST", IMPORTS, json=body))["id"]

    async def manifest(self, job_id: str, entries: list[dict]) -> list[dict]:
        results: list[dict] = []
        for i in range(0, len(entries), MANIFEST_CHUNK):
            chunk = entries[i : i + MANIFEST_CHUNK]
            body = await self.ok("POST", f"{IMPORTS}/{job_id}/manifest", json={"files": chunk})
            results.extend(body["items"])
        return results

    async def archive(self, job_id: str, name: str, data: bytes) -> httpx.Response:
        self.bytes_sent += len(data)
        return await self.req(
            "PUT", f"{IMPORTS}/{job_id}/archives", params={"name": name}, content=data
        )

    async def seal(self, job_id: str) -> dict:
        return await self.ok("POST", f"{IMPORTS}/{job_id}/seal", timeout=300)

    async def send_hashes(self, job_id: str, hashes: dict[int, str]) -> list[dict]:
        pairs = [{"item_id": k, "sha256": v} for k, v in hashes.items()]
        out: list[dict] = []
        for i in range(0, len(pairs), HASH_CHUNK):
            body = await self.ok(
                "POST", f"{IMPORTS}/{job_id}/hashes", json={"items": pairs[i : i + HASH_CHUNK]}
            )
            out.extend(body["items"])
        return out

    async def put(self, job_id: str, item_id: int, data: bytes) -> httpx.Response:
        """PUT one file's bytes, retrying transport errors (the endpoint is idempotent)."""
        for attempt in range(5):
            try:
                self.bytes_sent += len(data)
                return await self.req(
                    "PUT", f"{IMPORTS}/{job_id}/items/{item_id}/content", content=data
                )
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError):
                # Connection-level failures only: a timeout means the server is
                # stuck, which retrying would just hide.
                if attempt == 4:
                    raise
                await asyncio.sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")

    async def upload(
        self,
        job_id: str,
        payloads: dict[int, bytes],
        concurrency: int = UPLOAD_CONCURRENCY,
    ) -> dict[int, httpx.Response]:
        """Upload many items with a bounded number of PUTs in flight."""
        sem = asyncio.Semaphore(concurrency)
        responses: dict[int, httpx.Response] = {}

        async def one(item_id: int, data: bytes) -> None:
            async with sem:
                responses[item_id] = await self.put(job_id, item_id, data)

        await asyncio.gather(*(one(i, d) for i, d in payloads.items()))
        return responses

    async def job(self, job_id: str) -> dict:
        return await self.ok("GET", f"{IMPORTS}/{job_id}")

    async def items(self, job_id: str, states: Iterable[str] | None = None) -> list[dict]:
        """Every item of a job (keyset pagination)."""
        out: list[dict] = []
        after = 0
        params: list[tuple[str, Any]] = [("state", s) for s in states or ()]
        while True:
            page = await self.ok(
                "GET",
                f"{IMPORTS}/{job_id}/items",
                params=[*params, ("after", after), ("limit", 1000)],
            )
            out.extend(page["items"])
            if page["next_after"] is None:
                return out
            after = page["next_after"]

    async def wait(
        self,
        job_ids: Iterable[str],
        timeout: float = 600,
        until: Callable[[dict], bool] = settled,
        interval: float = 0.25,
    ) -> dict[str, dict]:
        """Poll ``GET /imports`` (with ETag, like the frontend) until ``until`` holds for
        every job, then return their details."""
        pending = set(job_ids)
        etag: str | None = None
        deadline = time.monotonic() + timeout
        last: dict[str, dict] = {}
        while pending:
            if time.monotonic() > deadline:
                stuck = {
                    j: (last.get(j, {}).get("status"), last.get(j, {}).get("counts"))
                    for j in pending
                }
                raise TimeoutError(f"{len(pending)} job(s) not settled after {timeout}s: {stuck}")
            headers = {"If-None-Match": etag} if etag else {}
            r = await self.req(
                "GET", IMPORTS, params={"limit": 200, "include_dismissed": True}, headers=headers
            )
            self.poll.polls += 1
            if r.status_code == 304:
                self.poll.not_modified += 1
            elif r.status_code == 200:
                etag = r.headers.get("etag")
                listed = {j["id"]: j for j in r.json()["jobs"]}
                for job_id in list(pending):
                    job = listed.get(job_id) or await self.job(job_id)
                    last[job_id] = job
                    if until(job):
                        pending.discard(job_id)
            if pending:
                await asyncio.sleep(interval)
        return {job_id: await self.job(job_id) for job_id in job_ids}

    async def wait_one(self, job_id: str, **kwargs) -> dict:
        return (await self.wait([job_id], **kwargs))[job_id]

    async def action(self, job_id: str, name: str, body: dict | None = None) -> httpx.Response:
        return await self.req("POST", f"{IMPORTS}/{job_id}/{name}", json=body)

    async def undo(self, job_id: str, timeout: float = 60) -> httpx.Response:
        """DELETE (undo), retrying the 409 returned while a batch is mid-flight."""
        deadline = time.monotonic() + timeout
        while True:
            r = await self.req("DELETE", f"{IMPORTS}/{job_id}")
            if r.status_code != 409 or time.monotonic() > deadline:
                return r
            await asyncio.sleep(0.25)

    async def start(
        self,
        files: list[tuple[str, bytes]],
        *,
        label: str,
        image_type: str = "battlemap",
        extra_manifest: list[dict] | None = None,
    ) -> StartedImport:
        """Create, manifest and seal a job for ``files`` (no bytes sent yet)."""
        job_id = await self.create(label, image_type)
        manifest = await self.manifest(job_id, entries(files) + (extra_manifest or []))
        await self.seal(job_id)
        return StartedImport(job_id, manifest)

    async def supply(
        self,
        started: StartedImport,
        files: list[tuple[str, bytes]],
        *,
        use_hashes: bool = True,
        concurrency: int = UPLOAD_CONCURRENCY,
    ) -> dict[int, httpx.Response]:
        """Send hashes (skipping known files), then upload the rest."""
        ids = started.item_ids
        payloads = {ids[path]: data for path, data in files if path in ids}
        if use_hashes and payloads:
            results = await self.send_hashes(
                started.job_id, {i: sha256(d) for i, d in payloads.items()}
            )
            for res in results:
                if res["state"] != "awaiting_bytes":
                    payloads.pop(res["item_id"], None)
        return await self.upload(started.job_id, payloads, concurrency)

    async def run_import(
        self,
        files: list[tuple[str, bytes]],
        *,
        label: str,
        use_hashes: bool = True,
        image_type: str = "battlemap",
        timeout: float = 600,
    ) -> dict:
        started = await self.start(files, label=label, image_type=image_type)
        await self.supply(started, files, use_hashes=use_hashes)
        return await self.wait_one(started.job_id, timeout=timeout)


class Library:
    """Read-only view of the server's SQLite DB and file stores, for integrity checks."""

    def __init__(self, server: StressTestServer) -> None:
        self.server = server

    def query(self, sql: str, args: tuple = ()) -> list[tuple]:
        db = self.server.data_dir / "battlemap.db"
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def scalar(self, sql: str, args: tuple = ()) -> Any:
        return self.query(sql, args)[0][0]

    def images(self, job_id: str | None = None) -> int:
        if job_id is None:
            return self.scalar("SELECT COUNT(*) FROM images")
        return self.scalar("SELECT COUNT(*) FROM images WHERE import_job_id = ?", (job_id,))

    def duplicate_hashes(self) -> int:
        """Content hashes held by more than one image (should be 0 without import-as-copy)."""
        return self.scalar(
            "SELECT COUNT(*) FROM (SELECT content_hash FROM images "
            "WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING COUNT(*) > 1)"
        )

    def stored_files(self) -> int:
        """Files in the library's ``xx/yy/<key>`` shard layout."""
        root = self.server.library_dir
        return sum(
            1
            for p in root.glob("*/*/*")
            if p.is_file() and p.relative_to(root).parts[0] not in ("backups", ".incoming")
        )

    def thumbnails(self) -> int:
        root = self.server.data_dir / "store" / "thumbnails"
        return sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0

    def staged_files(self, job_id: str) -> int:
        root = self.server.data_dir / "staging" / job_id
        return sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0

    def integrity(self, check: Check, *, expect_images: int, unique_hashes: bool = True) -> None:
        """Rows, stored files and thumbnails agree; no leftover temp files."""
        images = self.images()
        check.eq(images, expect_images, "image rows")
        check.eq(self.stored_files(), images, "stored files vs image rows")
        thumbs = self.thumbnails()
        check(thumbs >= images, f"thumbnails ({thumbs}) fewer than images ({images})")
        if unique_hashes:
            check.eq(self.duplicate_hashes(), 0, "content hashes shared by several images")
        incoming = self.server.library_dir / ".incoming"
        leftovers = sum(1 for p in incoming.rglob("*") if p.is_file()) if incoming.exists() else 0
        check.eq(leftovers, 0, "leftover .incoming temp files")


@dataclass
class Env:
    """Per-scenario conveniences: a client, stats, a checker and the library view."""

    ctx: ScenarioContext
    stats: RequestStats = field(default_factory=RequestStats)
    check: Check = field(default_factory=Check)

    @property
    def fixtures(self) -> FixturePaths:
        return self.ctx.fixtures  # type: ignore[return-value]

    @property
    def lib(self) -> Library:
        return Library(self.ctx.server)

    def scale(self, quick: int, default: int, large: int | None = None) -> int:
        if self.ctx.quick_mode:
            return quick
        if self.ctx.large_mode and large is not None:
            return large
        return default

    def client(self, timeout: float = 120) -> httpx.AsyncClient:
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=32)
        return httpx.AsyncClient(base_url=self.ctx.base_url, timeout=timeout, limits=limits)

    def finish(self, name: str, api: ImportClient | None, ok_message: str) -> ScenarioResult:
        if api is not None:
            self.check(
                not api.unexpected, "unexpected errors:\n  " + "\n  ".join(api.unexpected[:10])
            )
        return self.check.result(name, self.stats, ok_message)


async def happy_path(ctx: ScenarioContext) -> ScenarioResult:
    """One import end to end; measures setup, upload and processing throughput."""
    env = Env(ctx)
    n = env.scale(100, 500, 2000)
    files = image_set(n, 1_000_000, folder="Throughput Author/Throughput Pack")
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        t0 = time.monotonic()
        started = await api.start(files, label="happy path")
        t_setup = time.monotonic() - t0
        await api.supply(started, files)
        t_upload = time.monotonic() - t0
        job = await api.wait_one(started.job_id)
        t_total = time.monotonic() - t0

        c = job["counts"]
        env.check.eq(job["status"], "completed", "status")
        env.check.eq(c["done"], n, "done")
        env.check.eq(c["total"], n, "total")
        env.check.eq(env.lib.images(started.job_id), n, "images for job")
        env.check.eq(sum(g["counts"]["done"] for g in job["groups"]), n, "group done sum")
        env.lib.integrity(env.check, expect_images=n)
        env.check.note(
            f"{n} files: setup {t_setup:.1f}s, uploaded by {t_upload:.1f}s, done at "
            f"{t_total:.1f}s ({n / t_total:.1f} img/s); polls {api.poll.polls}, "
            f"304s {api.poll.not_modified}"
        )
    return env.finish("happy_path", api, f"{n}/{n} imported")


async def large_manifest(ctx: ScenarioContext) -> ScenarioResult:
    """Many thousands of items (chunked manifest), a subset uploaded, the rest finished-without."""
    env = Env(ctx)
    total = env.scale(5_000, 10_000, 40_000)  # --large crosses SQLite's 32,766 variable limit
    uploaded = env.scale(100, 400, 1_000)
    groups = 50
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        job_id = await api.create("large manifest")
        upload_files = {
            f"Manifest Author/Pack {i % groups:02d}/map_{i:06d}.jpg": noise_jpeg(2_000_000 + i)
            for i in range(uploaded)
        }
        paths = [f"Manifest Author/Pack {i % groups:02d}/map_{i:06d}.jpg" for i in range(total)]
        entries = [
            {"relative_path": p, "size": len(upload_files[p]) if p in upload_files else 50_000}
            for p in paths
        ]
        t0 = time.monotonic()
        chunk_times = []
        manifest: list[dict] = []
        for i in range(0, total, MANIFEST_CHUNK):
            t = time.monotonic()
            manifest.extend(await api.manifest(job_id, entries[i : i + MANIFEST_CHUNK]))
            chunk_times.append(time.monotonic() - t)
        t_manifest = time.monotonic() - t0
        env.check.eq(len(manifest), total, "manifest items created")

        # Re-sending a chunk is ignored (paths already in the job), not duplicated.
        again = await api.ok(
            "POST", f"{IMPORTS}/{job_id}/manifest", json={"files": entries[:MANIFEST_CHUNK]}
        )
        env.check.eq((len(again["items"]), again["ignored"]), (0, MANIFEST_CHUNK), "re-sent chunk")

        t = time.monotonic()
        detail = await api.seal(job_id)
        t_seal = time.monotonic() - t
        env.check.eq(len(detail["groups"]), groups, "planned groups")

        t = time.monotonic()
        all_items = await api.items(job_id)
        t_items = time.monotonic() - t
        env.check.eq(len(all_items), total, "paginated items")

        t = time.monotonic()
        await api.req("GET", IMPORTS)
        t_list = time.monotonic() - t

        await api.supply(StartedImport(job_id, manifest), list(upload_files.items()))
        await api.wait(
            [job_id],
            until=lambda j: j["counts"]["done"] + j["counts"]["failed"] >= uploaded,
        )
        r = await api.action(job_id, "finish-upload")
        env.check.eq(r.status_code, 200, "finish-upload")
        job = await api.wait_one(job_id)
        c = job["counts"]
        env.check.eq(job["status"], "completed", "status")
        env.check.eq(c["done"], uploaded, "done")
        env.check.eq(c["skipped"], total - uploaded, "skipped (not uploaded)")
        env.lib.integrity(env.check, expect_images=uploaded)
        env.check.note(
            f"{total} items: manifest {t_manifest:.1f}s (chunk max {max(chunk_times):.2f}s), "
            f"seal {t_seal:.1f}s, list all items {t_items:.1f}s, GET /imports {t_list * 1000:.0f}ms"
        )
    return env.finish("large_manifest", api, f"{total} items, {uploaded} uploaded")


async def concurrent_imports(ctx: ScenarioContext) -> ScenarioResult:
    """Many jobs started and uploaded at once (SQLite write contention, worker fairness)."""
    env = Env(ctx)
    jobs = env.scale(10, 50, 100)
    per_job = 5
    async with env.client() as http:
        api = ImportClient(http, env.stats)

        async def one(idx: int) -> str:
            files = image_set(per_job, 3_000_000 + idx * per_job, folder=f"Concurrent/Pack {idx}")
            started = await api.start(files, label=f"concurrent {idx}")
            await api.supply(started, files, concurrency=2)
            return started.job_id

        t0 = time.monotonic()
        results = await asyncio.gather(*(one(i) for i in range(jobs)), return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        env.check(not errors, f"{len(errors)} job flows raised: {errors[:3]}")
        job_ids = [r for r in results if isinstance(r, str)]
        final = await api.wait(job_ids)
        elapsed = time.monotonic() - t0
        not_done = [j for j in final.values() if j["counts"]["done"] != per_job]
        env.check(
            not not_done,
            f"{len(not_done)} job(s) incomplete: {[j['counts'] for j in not_done[:3]]}",
        )
        env.lib.integrity(env.check, expect_images=jobs * per_job)
        env.check.note(f"{jobs}×{per_job} files in {elapsed:.1f}s")
    return env.finish("concurrent_imports", api, f"{jobs} jobs completed")


async def round_robin_fairness(ctx: ScenarioContext) -> ScenarioResult:
    """Small imports started behind a big one finish long before it (round-robin claims)."""
    env = Env(ctx)
    big_n = env.scale(240, 600, 1500)
    small_jobs, small_n = 4, 3
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        big_files = image_set(big_n, 4_000_000, folder="Fair/Big Pack", width=480, height=360)
        big = await api.start(big_files, label="big")
        await api.supply(big, big_files)
        await api.wait_one(big.job_id, until=done_at_least(BATCH_SIZE))

        async def small(idx: int) -> tuple[str, float]:
            t = time.monotonic()
            files = image_set(small_n, 4_100_000 + idx * 10, folder=f"Fair/Small {idx}")
            final = await api.run_import(files, label=f"small {idx}")
            env.check.eq(final["counts"]["done"], small_n, f"small job {idx} done")
            return final["id"], time.monotonic() - t

        latencies = await asyncio.gather(*(small(i) for i in range(small_jobs)))
        big_now = await api.job(big.job_id)
        remaining = big_n - big_now["counts"]["done"]
        env.check(
            big_now["status"] == "active" and remaining > 0,
            f"big job finished before the small ones could prove fairness ({big_now['counts']}); "
            "increase its size",
        )
        final = await api.wait_one(big.job_id)
        env.check.eq(final["counts"]["done"], big_n, "big job done")
        worst = max(t for _, t in latencies)
        env.check.note(
            f"small jobs done in ≤{worst:.1f}s while big still had {remaining}/{big_n} left"
        )
        env.lib.integrity(env.check, expect_images=big_n + small_jobs * small_n)
    return env.finish("round_robin_fairness", api, "small jobs not starved")


async def endpoint_spam(ctx: ScenarioContext) -> ScenarioResult:
    """Identical requests fired concurrently: seal, PUT, cancel, manifest-after-seal, polls, undo."""
    env = Env(ctx)
    n = env.scale(20, 100)
    check = env.check
    async with env.client(timeout=120) as http:
        api = ImportClient(http, env.stats)

        async def spam(make: Callable[[], Awaitable[httpx.Response]]) -> list[int]:
            return [r.status_code for r in await asyncio.gather(*(make() for _ in range(n)))]

        # 1. Concurrent seals are idempotent: one plan, one set of groups.
        files = image_set(3, 5_000_000, folder="Spam/Seal")
        job_id = await api.create("spam seal")
        await api.manifest(job_id, entries(files))
        codes = await spam(lambda: api.req("POST", f"{IMPORTS}/{job_id}/seal"))
        check(set(codes) == {200}, f"concurrent seal codes {sorted(set(codes))}")
        detail = await api.job(job_id)
        check.eq(len(detail["groups"]), 1, "groups after concurrent seals")

        # 2. Concurrent PUTs of the same item: one image.
        items = await api.items(job_id)
        target = items[0]
        data = dict(files)[target["relative_path"]]
        codes = await spam(lambda: api.put(job_id, target["id"], data))
        check(set(codes) == {200}, f"concurrent PUT codes {sorted(set(codes))}")
        rest = {i["id"]: dict(files)[i["relative_path"]] for i in items[1:]}
        await api.upload(job_id, rest)
        final = await api.wait_one(job_id)
        check.eq(final["counts"]["done"], 3, "done after concurrent PUTs")
        check.eq(env.lib.images(job_id), 3, "images after concurrent PUTs")

        # 3. Manifest after seal → 409 every time.
        codes = await spam(
            lambda: api.req(
                "POST",
                f"{IMPORTS}/{job_id}/manifest",
                json={"files": [{"relative_path": "Spam/late.jpg", "size": 1}]},
            )
        )
        check(set(codes) == {409}, f"manifest-after-seal codes {sorted(set(codes))}")

        # 4. Concurrent cancels of a sealed, un-uploaded job.
        files2 = image_set(5, 5_100_000, folder="Spam/Cancel")
        started = await api.start(files2, label="spam cancel")
        codes = await spam(lambda: api.action(started.job_id, "cancel"))
        check(set(codes) == {200}, f"concurrent cancel codes {sorted(set(codes))}")
        job = await api.job(started.job_id)
        check.eq((job["status"], job["counts"]["skipped"]), ("cancelled", 5), "after cancels")

        # 5. PUTs to a cancelled job's items → 409, nothing processed.
        some_id = next(iter(started.item_ids.values()))
        codes = await spam(lambda: api.put(started.job_id, some_id, files2[0][1]))
        check(set(codes) == {409}, f"PUT-to-cancelled codes {sorted(set(codes))}")
        check.eq(env.lib.images(started.job_id), 0, "images in cancelled job")

        # 6. Polls with and without ETag while idle.
        first = await api.req("GET", IMPORTS)
        etag = first.headers.get("etag")
        check(etag is not None, "GET /imports has no ETag")
        codes = await spam(lambda: api.req("GET", IMPORTS, headers={"If-None-Match": etag or ""}))
        check(set(codes) <= {200, 304} and 304 in codes, f"ETag poll codes {sorted(set(codes))}")
        codes = await spam(lambda: api.req("GET", f"{IMPORTS}/{job_id}"))
        check(set(codes) == {200}, f"detail poll codes {sorted(set(codes))}")

        # 7. Concurrent undo: one deletes, the rest find nothing.
        codes = await spam(lambda: api.req("DELETE", f"{IMPORTS}/{job_id}"))
        check(codes.count(200) == 1, f"concurrent undo: {codes.count(200)} × 200")
        check(set(codes) <= {200, 404, 409}, f"concurrent undo codes {sorted(set(codes))}")
        check.eq(env.lib.images(), 0, "images after undo")
    return env.finish("endpoint_spam", api, f"{n}× concurrency across 7 sub-tests")


async def cancellation_chaos(ctx: ScenarioContext) -> ScenarioResult:
    """Cancel before seal, before upload, mid-processing and after completion."""
    env = Env(ctx)
    check = env.check
    async with env.client() as http:
        api = ImportClient(http, env.stats)

        # (a) before seal
        files = image_set(3, 6_000_000, folder="Cancel/A")
        job_a = await api.create("cancel a")
        manifest = await api.manifest(job_a, entries(files))
        r = await api.action(job_a, "cancel")
        check.eq(r.status_code, 200, "(a) cancel before seal")
        r = await api.put(job_a, manifest[0]["item_id"], files[0][1])
        check.eq(r.status_code, 409, "(a) PUT after cancel")
        job = await api.job(job_a)
        check.eq((job["status"], job["counts"]["skipped"]), ("cancelled", 3), "(a) state")

        # (b) after seal, before upload
        files = image_set(5, 6_100_000, folder="Cancel/B")
        b = await api.start(files, label="cancel b")
        await api.action(b.job_id, "cancel")
        job = await api.job(b.job_id)
        check.eq((job["status"], job["counts"]["skipped"]), ("cancelled", 5), "(b) state")

        # (c) mid-processing: finished work is kept, the rest skipped
        n = env.scale(200, 400)
        files = image_set(n, 6_200_000, folder="Cancel/C", width=480, height=360)
        c = await api.start(files, label="cancel c")
        await api.supply(c, files)
        await api.wait_one(c.job_id, until=done_at_least(BATCH_SIZE))
        r = await api.action(c.job_id, "cancel")
        check.eq(r.status_code, 200, "(c) cancel mid-processing")
        job = await api.wait_one(c.job_id)
        cc = job["counts"]
        check.eq(job["status"], "cancelled", "(c) status")
        check(0 < cc["done"] < n, f"(c) expected some but not all done: {cc}")
        check.eq(cc["done"] + cc["skipped"], n, "(c) done + skipped")
        check.eq(env.lib.images(c.job_id), cc["done"], "(c) images kept")
        check.eq(env.lib.staged_files(c.job_id), 0, "(c) staged files left after cancel")
        r = await api.action(c.job_id, "retry")
        check.eq(r.status_code, 409, "(c) retry on cancelled job")
        check.note(f"(c) kept {cc['done']}/{n}")

        # (d) after completion: a no-op
        files = image_set(2, 6_300_000, folder="Cancel/D")
        final = await api.run_import(files, label="cancel d")
        r = await api.action(final["id"], "cancel")
        check.eq(r.status_code, 200, "(d) cancel after completion")
        job = await api.job(final["id"])
        check.eq((job["status"], job["counts"]["done"]), ("completed", 2), "(d) state")
        env.lib.integrity(env.check, expect_images=cc["done"] + 2)
    return env.finish("cancellation_chaos", api, "4 cancellation points correct")


async def pause_resume(ctx: ScenarioContext) -> ScenarioResult:
    """A paused job claims nothing; resume finishes it. Pausing mid-run lets at most a batch finish."""
    env = Env(ctx)
    check = env.check
    async with env.client() as http:
        api = ImportClient(http, env.stats)

        # Paused before any bytes arrive: uploads are accepted but nothing is processed.
        n = 48
        files = image_set(n, 7_000_000, folder="Pause/Before")
        a = await api.start(files, label="pause before")
        r = await api.action(a.job_id, "pause")
        check.eq(r.json().get("status"), "paused", "pause response")
        await api.supply(a, files)
        await asyncio.sleep(3)
        job = await api.job(a.job_id)
        check.eq(
            (job["status"], job["counts"]["done"], job["counts"]["ready"]),
            ("paused", 0, n),
            "paused",
        )
        await api.action(a.job_id, "resume")
        job = await api.wait_one(a.job_id)
        check.eq((job["status"], job["counts"]["done"]), ("completed", n), "after resume")

        # Paused mid-processing: progress stops within one batch.
        m = env.scale(200, 400)
        files = image_set(m, 7_100_000, folder="Pause/Mid", width=480, height=360)
        b = await api.start(files, label="pause mid")
        await api.supply(b, files)
        await api.wait_one(b.job_id, until=done_at_least(BATCH_SIZE))
        await api.action(b.job_id, "pause")
        at_pause = (await api.job(b.job_id))["counts"]["done"]
        await asyncio.sleep(2)
        d1 = (await api.job(b.job_id))["counts"]
        await asyncio.sleep(3)
        d2 = (await api.job(b.job_id))["counts"]
        check(
            d1["done"] - at_pause <= BATCH_SIZE,
            f"more than a batch finished after pause: {at_pause}→{d1['done']}",
        )
        check.eq(d2["done"], d1["done"], "done count while paused")
        check.eq(d2["processing"], 0, "processing while paused")
        if d2["done"] >= m:
            check.note("mid job finished before pause took effect (increase size)")
        await api.action(b.job_id, "resume")
        job = await api.wait_one(b.job_id)
        check.eq((job["status"], job["counts"]["done"]), ("completed", m), "mid after resume")
        env.lib.integrity(check, expect_images=n + m)
    return env.finish("pause_resume", api, "pause holds, resume completes")


async def reimport_duplicates(ctx: ScenarioContext) -> ScenarioResult:
    """Byte duplicates (client hash and server receipt), in-job duplicates and pixel duplicates."""
    env = Env(ctx)
    check = env.check
    n = 40
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        files = image_set(n, 8_000_000, folder="Dup/Original")
        first = await api.run_import(files, label="original")
        check.eq(first["counts"]["done"], n, "original done")

        # Same files again with client hashes: no bytes sent at all.
        renamed = [(p.replace("Original", "Again"), d) for p, d in files]
        sent_before = api.bytes_sent
        again = await api.run_import(renamed, label="again (hashes)")
        check.eq(again["counts"]["duplicate"], n, "client-hash duplicates")
        check.eq(api.bytes_sent - sent_before, 0, "bytes uploaded for known files")
        check.eq(again["status"], "completed", "all-duplicate job completes")

        # Same files with bytes (no client hashing, e.g. plain-HTTP LAN origin).
        again2 = await api.run_import(renamed, label="again (bytes)", use_hashes=False)
        check.eq(again2["counts"]["duplicate"], n, "server-side byte duplicates")

        # Within one job: the same bytes under two paths.
        fresh = image_set(10, 8_100_000, folder="Dup/InJob A")
        twins = [(p.replace("InJob A", "InJob B"), d) for p, d in fresh]
        injob = await api.run_import(fresh + twins, label="in-job", use_hashes=False)
        check.eq(
            (injob["counts"]["done"], injob["counts"]["duplicate"]), (10, 10), "in-job duplicates"
        )

        # Pixel tier: same pixels, different PNG compression → different bytes.
        png_a = [
            (f"Dup/Png/a_{i}.png", noise_png(8_200_000 + i, compress_level=9)) for i in range(10)
        ]
        png_b = [
            (f"Dup/Png2/b_{i}.png", noise_png(8_200_000 + i, compress_level=1)) for i in range(10)
        ]
        check(
            all(sha256(a[1]) != sha256(b[1]) for a, b in zip(png_a, png_b, strict=True)),
            "PNG bytes should differ",
        )
        pa = await api.run_import(png_a, label="png a")
        pb = await api.run_import(png_b, label="png b")
        check.eq(pa["counts"]["done"], 10, "png a done")
        check.eq(pb["counts"]["duplicate"], 10, "pixel-tier duplicates")
        tiers = {i["duplicate_tier"] for i in await api.items(pb["id"], ["duplicate"])}
        check.eq(tiers, {"pixels"}, "pixel duplicate tier")

        env.lib.integrity(check, expect_images=n + 10 + 10)
    return env.finish("reimport_duplicates", api, "all duplicate tiers skipped")


async def import_as_copy(ctx: ScenarioContext) -> ScenarioResult:
    """Duplicates imported as new copies become fully independent images."""
    env = Env(ctx)
    check = env.check
    n = 20
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        files = image_set(n, 9_000_000, folder="Copy/Original")
        await api.run_import(files, label="original")

        # Skipped via client hash: no staged bytes, so the copy needs an upload.
        b_files = [(p.replace("Original", "B"), d) for p, d in files]
        b = await api.run_import(b_files, label="copy b")
        check.eq(b["counts"]["duplicate"], n, "b duplicates")
        r = await api.action(b["id"], "import-as-copy")
        check.eq(r.json().get("affected"), n, "b import-as-copy affected")
        awaiting = await api.items(b["id"], ["awaiting_bytes"])
        check.eq(len(awaiting), n, "b items awaiting bytes")
        by_path = dict(b_files)
        await api.upload(b["id"], {i["id"]: by_path[i["relative_path"]] for i in awaiting})
        b = await api.wait_one(b["id"])
        check.eq(b["counts"]["done"], n, "b copies done")

        # Duplicate detected on receipt: staged bytes kept, no re-upload needed.
        c_files = [(p.replace("Original", "C"), d) for p, d in files]
        c = await api.run_import(c_files, label="copy c", use_hashes=False)
        check.eq(c["counts"]["duplicate"], n, "c duplicates")
        sent = api.bytes_sent
        await api.action(c["id"], "import-as-copy")
        c = await api.wait_one(c["id"])
        check.eq(c["counts"]["done"], n, "c copies done")
        check.eq(api.bytes_sent, sent, "bytes re-sent for c")

        lib = env.lib
        check.eq(lib.images(), 3 * n, "image rows")
        check.eq(
            lib.scalar("SELECT COUNT(DISTINCT storage_key) FROM images"),
            3 * n,
            "distinct stored files",
        )
        check.eq(
            lib.scalar(
                "SELECT COUNT(*) FROM (SELECT content_hash FROM images GROUP BY content_hash HAVING COUNT(*) = 3)"
            ),
            n,
            "hashes held by exactly 3 images",
        )
        lib.integrity(check, expect_images=3 * n, unique_hashes=False)
    return env.finish("import_as_copy", api, f"{2 * n} independent copies")


async def undo_import(ctx: ScenarioContext) -> ScenarioResult:
    """DELETE removes exactly the job's images, files, thumbnails and created groups."""
    env = Env(ctx)
    check = env.check
    lib = env.lib
    async with env.client() as http:
        api = ImportClient(http, env.stats)

        # A keeper job, then a second job that merges into the keeper's group.
        keep = await api.run_import(image_set(10, 10_000_000, folder="Undo/Shared"), label="keep")
        merged = await api.run_import(
            image_set(15, 10_100_000, folder="Undo/Shared"), label="merged"
        )
        check(
            any(g["merged_into_existing"] for g in merged["groups"]),
            "second job should merge into the existing group",
        )
        groups_before = lib.scalar("SELECT COUNT(*) FROM variant_groups")

        r = await api.undo(merged["id"])
        check.eq((r.status_code, r.json().get("affected")), (200, 15), "undo merged job")
        check.eq(
            (await api.req("GET", f"{IMPORTS}/{merged['id']}")).status_code, 404, "undone job gone"
        )
        check.eq(lib.images(), 10, "images after undoing merged job")
        check.eq(
            lib.scalar("SELECT COUNT(*) FROM variant_groups"), groups_before, "shared group kept"
        )

        # Undo while processing (409 until the in-flight batch commits).
        n = env.scale(150, 300)
        files = image_set(n, 10_200_000, folder="Undo/Busy", width=480, height=360)
        busy = await api.start(files, label="busy")
        await api.supply(busy, files)
        await api.wait_one(busy.job_id, until=done_at_least(BATCH_SIZE))
        t = time.monotonic()
        r = await api.undo(busy.job_id)
        check.eq(r.status_code, 200, "undo mid-processing")
        check.note(
            f"mid-processing undo took {time.monotonic() - t:.1f}s, removed {r.json().get('affected')}"
        )
        await asyncio.sleep(2)  # anything still in flight would land now
        check.eq(lib.images(busy.job_id), 0, "images of undone busy job")
        check.eq(lib.staged_files(busy.job_id), 0, "staging of undone busy job")

        # Undo the keeper too: the store is empty again.
        r = await api.undo(keep["id"])
        check.eq(r.status_code, 200, "undo keeper")
        check.eq(lib.scalar("SELECT COUNT(*) FROM variant_groups"), 0, "groups after undoing all")
        check.eq(lib.thumbnails(), 0, "thumbnails after undoing all")
        lib.integrity(check, expect_images=0)
    return env.finish("undo_import", api, "undo removed exactly the job's work")


async def retry_failed(ctx: ScenarioContext) -> ScenarioResult:
    """Failed items retry: validation failures need new bytes, worker failures reuse staged ones."""
    env = Env(ctx)
    check = env.check
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        good = image_set(10, 11_000_000, folder="Retry/Pack")
        fixable = image_set(5, 11_100_000, folder="Retry/Pack Fixable")
        corrupt = [
            # Truncated real JPEGs: the header passes validation, decoding fails in the worker.
            (f"Retry/Pack/corrupt_{i}.jpg", noise_jpeg(11_200_000 + i, 640, 480)[:4000])
            for i in range(3)
        ]
        started = await api.start(good + fixable + corrupt, label="retry")
        # Fixable files first arrive as non-images (e.g. a broken download),
        # interleaved with good files so validating unidentifiable bytes overlaps
        # the worker's processing. That once deadlocked the server: PIL's first
        # plugin dlopen vs sklearn/threadpoolctl's dl_iterate_phdr.
        garbage = {started.item_ids[p]: b"not an image at all" * 50 for p, _ in fixable}
        await api.upload(started.job_id, {started.item_ids[p]: d for p, d in good[:5]})
        mixed: dict[int, bytes] = {}
        for (path, data), gid in zip(good[5:], garbage, strict=True):
            mixed[started.item_ids[path]] = data
            mixed[gid] = garbage[gid]
        mixed.update({started.item_ids[p]: d for p, d in corrupt})
        responses = await api.upload(started.job_id, mixed)
        check(
            all(responses[i].json()["state"] == "failed" for i in garbage),
            "garbage bytes should fail validation",
        )
        job = await api.wait_one(started.job_id)
        check.eq((job["counts"]["done"], job["counts"]["failed"]), (10, 8), "first pass")
        kinds = {i["error_kind"] for i in await api.items(started.job_id, ["failed"])}
        check.eq(kinds, {"file"}, "failure kinds")

        r = await api.action(started.job_id, "retry")
        check.eq(
            (r.json().get("affected"), r.json().get("status")), (8, "active"), "retry re-opens job"
        )
        awaiting = await api.items(started.job_id, ["awaiting_bytes"])
        check.eq(len(awaiting), 5, "validation failures need bytes again")
        fixed = dict(fixable)
        await api.upload(started.job_id, {i["id"]: fixed[i["relative_path"]] for i in awaiting})
        job = await api.wait_one(started.job_id)
        check.eq(
            (job["status"], job["counts"]["done"], job["counts"]["failed"]),
            ("completed", 15, 3),
            "after retry",
        )
        env.lib.integrity(check, expect_images=15)
    return env.finish("retry_failed", api, "retry recovered fixable files")


async def interrupted_upload_resume(ctx: ScenarioContext) -> ScenarioResult:
    """The client vanishes mid-upload; a new client resumes from the server's item list."""
    env = Env(ctx)
    check = env.check
    n = 60
    files = image_set(n, 12_000_000, folder="Resume/Pack")
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        started = await api.start(files, label="resume")
        await api.supply(started, files[:20])
        job = await api.wait_one(started.job_id, until=done_at_least(20))
        check.eq(
            (job["status"], job["counts"]["awaiting_bytes"]), ("active", 40), "job waits for bytes"
        )

    # "Another tab": knows only the job id and the files on disk.
    async with env.client() as http:
        api2 = ImportClient(http, env.stats)
        local = dict(files)
        awaiting = await api2.items(started.job_id, ["awaiting_bytes"])
        check.eq(len(awaiting), 40, "awaiting items listed")
        resume = {
            i["id"]: local[i["relative_path"]]
            for i in awaiting[:20]
            if i["size"] == len(local[i["relative_path"]])
        }
        await api2.upload(started.job_id, resume)
        # Re-sending bytes of finished items is a harmless no-op.
        replay = await api2.upload(started.job_id, {started.item_ids[p]: d for p, d in files[:5]})
        check(all(r.status_code == 200 for r in replay.values()), "re-PUT of done items")
        await api2.wait_one(started.job_id, until=done_at_least(40))
        r = await api2.action(started.job_id, "finish-upload")
        check.eq(r.json().get("affected"), 20, "finish-upload skipped")
        job = await api2.wait_one(started.job_id)
        check.eq(
            (job["status"], job["counts"]["done"], job["counts"]["skipped"]),
            ("completed", 40, 20),
            "final",
        )
        env.lib.integrity(check, expect_images=40)
    return env.finish("interrupted_upload_resume", api2, "resumed 20, finished without 20")


async def zip_archives(ctx: ScenarioContext) -> ScenarioResult:
    """Archives expand server-side; bad archives and members become failed items, not job failures."""
    env = Env(ctx)
    check = env.check
    fx = env.fixtures
    large_count = fx.large_zip_count
    mixed = zip_bytes(
        [
            *image_set(5, 13_000_000, folder="ZipAuthor/Mixed Pack"),
            ("ZipAuthor/Mixed Pack/broken.jpg", b"definitely not a jpeg" * 100),
            ("ZipAuthor/Mixed Pack/readme.txt", b"hello"),
            ("__MACOSX/ZipAuthor/._map.jpg", b"junk"),
        ]
    )
    loose = image_set(5, 13_100_000, folder="Loose/Pack")
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        job_id = await api.create("zips")
        manifest = await api.manifest(job_id, entries(loose))
        results = {}
        t = time.monotonic()
        for name, data in [
            ("small.zip", fx.zip_small.read_bytes()),
            ("large.zip", fx.zip_large.read_bytes()),
            ("mixed.zip", mixed),
            ("malformed.zip", fx.malformed_zip.read_bytes()),
            ("near_bomb.zip", fx.zip_near_bomb.read_bytes()),
            # Path traversal anywhere rejects the whole archive.
            ("traversal.zip", zip_bytes([("../escape/evil.jpg", noise_jpeg(13_000_100))])),
        ]:
            r = await api.archive(job_id, name, data)
            check(r.status_code == 200, f"{name}: HTTP {r.status_code} {r.text[:200]}")
            results[name] = r.json() if r.status_code == 200 else None
        t_archives = time.monotonic() - t
        check.eq(results["small.zip"] and results["small.zip"]["created"], 10, "small.zip created")
        check.eq(
            results["large.zip"] and results["large.zip"]["created"],
            large_count,
            "large.zip created",
        )
        check.eq((results["malformed.zip"] or {}).get("failed"), 1, "malformed.zip failed")
        check.eq((results["near_bomb.zip"] or {}).get("failed"), 1, "near_bomb.zip failed")
        check.eq((results["traversal.zip"] or {}).get("failed"), 1, "traversal.zip failed")
        check.eq(
            results["mixed.zip"]
            and (results["mixed.zip"]["created"], results["mixed.zip"]["failed"]),
            (5, 1),
            "mixed.zip created/failed",
        )

        await api.seal(job_id)
        r = await api.archive(job_id, "late.zip", fx.zip_small.read_bytes())
        check.eq(r.status_code, 409, "archive after seal")
        await api.supply(StartedImport(job_id, manifest), loose)
        job = await api.wait_one(job_id)
        c = job["counts"]
        check.eq(job["status"], "completed", "status")
        expected_done = 10 + large_count + 5 + 5
        check.eq(c["done"], expected_done, "done")
        failed = await api.items(job_id, ["failed"])
        failed_archives = [i for i in failed if i["kind"] == "archive"]
        check.eq(len(failed_archives), 3, "failed archive items")
        check(
            any(i["relative_path"].endswith("broken.jpg") for i in failed),
            "broken.jpg member failed",
        )
        paths = [i["relative_path"] for i in await api.items(job_id)]
        check(not any(".." in p.split("/") for p in paths), "a member path still contains '..'")
        check.note(f"6 archives expanded in {t_archives:.1f}s; final counts {c}")
        env.lib.integrity(check, expect_images=c["done"])
    return env.finish("zip_archives", api, "archives expanded, bad ones isolated")


async def malformed_input(ctx: ScenarioContext) -> ScenarioResult:
    """Corrupt and mismatched files fail individually; the job completes; no 5xx."""
    env = Env(ctx)
    check = env.check
    fx = env.fixtures
    good = image_set(5, 14_000_000, folder="Malformed/Pack")
    bad = [
        ("Malformed/Pack/corrupt.jpg", fx.malformed_jpeg.read_bytes()),
        ("Malformed/Pack/corrupt.png", fx.malformed_png.read_bytes()),
        ("Malformed/Pack/corrupt.webp", fx.malformed_webp.read_bytes()),
        ("Malformed/Pack/corrupt.mp4", fx.malformed_mp4.read_bytes()),
        ("Malformed/Pack/corrupt.webm", fx.malformed_webm.read_bytes()),
        ("Malformed/Pack/text_as.png", b"just some text, not a png\n" * 40),
        ("Malformed/Pack/truncated.jpg", noise_jpeg(14_000_100, 640, 480)[:4000]),
    ]
    videos = [
        (f"Malformed/Pack/clip{p.suffix}", p.read_bytes())
        for p in (fx.video_mp4, fx.video_webm)
        if p is not None
    ]
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        extra = [
            {"relative_path": "Malformed/Pack/empty.jpg", "size": 0},
            {"relative_path": "Malformed/Pack/size_lies.jpg", "size": 10},
            {"relative_path": "Malformed/Pack/notes.txt", "size": 5},
            {"relative_path": "Malformed/Pack/._appledouble.jpg", "size": 4096},
            {"relative_path": "Malformed/Pack/huge.jpg", "size": 3 * 1024**3},
        ]
        started = await api.start(good + bad + videos, label="malformed", extra_manifest=extra)
        states = {m["relative_path"]: m["state"] for m in started.manifest}
        check(
            "Malformed/Pack/._appledouble.jpg" not in states, "AppleDouble file should be ignored"
        )
        check.eq(states.get("Malformed/Pack/notes.txt"), "skipped", "unsupported file state")
        check.eq(states.get("Malformed/Pack/huge.jpg"), "failed", "oversized manifest entry")
        await api.supply(started, good + bad + videos, use_hashes=False)

        r = await api.put(started.job_id, started.item_ids["Malformed/Pack/empty.jpg"], b"")
        check.eq(r.status_code, 400, "empty upload")
        lying = await api.put(
            started.job_id, started.item_ids["Malformed/Pack/size_lies.jpg"], noise_jpeg(14_000_200)
        )
        check.eq(
            (lying.status_code, lying.json().get("state")), (200, "failed"), "size-mismatch upload"
        )
        await api.action(started.job_id, "finish-upload")  # the empty file never arrives

        job = await api.wait_one(started.job_id)
        c = job["counts"]
        check.eq(job["status"], "completed", "status")
        failed = {i["relative_path"]: i for i in await api.items(started.job_id, ["failed"])}
        for path, _ in bad:
            check(path in failed, f"{path} should be failed")
        check(
            all(i["error_kind"] == "file" for i in failed.values()),
            f"failure kinds {[i['error_kind'] for i in failed.values()]}",
        )
        done_paths = {i["relative_path"] for i in await api.items(started.job_id, ["done"])}
        for path, _ in good + videos:
            check(path in done_paths, f"{path} should be done")
        check.note(f"counts {c}")
        env.lib.integrity(check, expect_images=c["done"])
    return env.finish("malformed_input", api, f"{len(bad)} corrupt files isolated")


async def duplicate_hash_race(ctx: ScenarioContext) -> ScenarioResult:
    """The same bytes uploaded to many jobs at once produce exactly one image."""
    env = Env(ctx)
    jobs = env.scale(10, 50)
    data = noise_jpeg(15_000_000, 320, 240)
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        started = await asyncio.gather(
            *(
                api.start([(f"Race/Pack {i}/same.jpg", data)], label=f"race {i}")
                for i in range(jobs)
            )
        )
        await asyncio.gather(
            *(
                api.supply(s, [(f"Race/Pack {i}/same.jpg", data)], use_hashes=False)
                for i, s in enumerate(started)
            )
        )
        final = await api.wait([s.job_id for s in started])
        done = sum(j["counts"]["done"] for j in final.values())
        dup = sum(j["counts"]["duplicate"] for j in final.values())
        env.check.eq((done, dup), (1, jobs - 1), "done/duplicate across jobs")
        env.check.eq(
            env.lib.scalar("SELECT COUNT(*) FROM images WHERE content_hash = ?", (sha256(data),)),
            1,
            "images with the shared hash",
        )
        env.lib.integrity(env.check, expect_images=1)
    return env.finish("duplicate_hash_race", api, f"{jobs} racing jobs → 1 image")


async def concurrent_move_groups(ctx: ScenarioContext) -> ScenarioResult:
    """Concurrent move-images requests for the same images: exactly one succeeds."""
    env = Env(ctx)
    check = env.check
    concurrency = 20
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        src = await api.run_import(image_set(4, 16_000_000, folder="Move/Source"), label="src")
        tgt = await api.run_import(image_set(2, 16_100_000, folder="Move/Target"), label="tgt")
        src_group = src["groups"][0]["image_group_id"]
        tgt_group = tgt["groups"][0]["image_group_id"]
        check(src_group and tgt_group, f"group ids missing: {src_group}, {tgt_group}")
        image_ids = [img["id"] for img in (await api.ok("GET", f"{GROUPS}/{src_group}"))["images"]]
        check.eq(len(image_ids), 4, "source images")

        async def move() -> int:
            r = await api.req(
                "POST",
                f"{GROUPS}/{src_group}/move-images",
                json={"target_group_id": tgt_group, "image_ids": image_ids},
            )
            return r.status_code

        codes = await asyncio.gather(*(move() for _ in range(concurrency)))
        check.eq(codes.count(200), 1, "successful moves")
        check(set(codes) <= {200, 400, 404, 409}, f"move codes {sorted(set(codes))}")
        tgt_ids = {img["id"] for img in (await api.ok("GET", f"{GROUPS}/{tgt_group}"))["images"]}
        check(set(image_ids) <= tgt_ids, "moved images missing from target")
    return env.finish("concurrent_move_groups", api, f"1/{concurrency} moves succeeded")


async def large_uploads(ctx: ScenarioContext) -> ScenarioResult:
    """Big files streamed concurrently (and, with --large, a 1000-image zip)."""
    env = Env(ctx)
    fx = env.fixtures
    files = [(f"Big/Pack/{p.name}", p.read_bytes()) for p in fx.big_jpegs]
    total_mb = sum(len(d) for _, d in files) / 1024**2
    async with env.client(timeout=1800) as http:
        api = ImportClient(http, env.stats)
        started = await api.start(files, label="big files")
        t = time.monotonic()
        await api.supply(started, files, use_hashes=False)
        t_up = time.monotonic() - t
        job = await api.wait_one(started.job_id, timeout=1800)
        t_all = time.monotonic() - t
        env.check.eq(job["counts"]["done"], len(files), "big files done")
        env.check.note(
            f"{total_mb:.0f} MB uploaded in {t_up:.1f}s ({total_mb / t_up:.0f} MB/s), processed by {t_all:.1f}s"
        )
        expected = len(files)
        if fx.large_mode:
            job_id = await api.create("big zip")
            r = await api.archive(job_id, "large.zip", fx.zip_large.read_bytes())
            env.check.eq(r.status_code, 200, "large zip upload")
            await api.seal(job_id)
            zjob = await api.wait_one(job_id, timeout=1800)
            env.check.eq(zjob["counts"]["done"], fx.large_zip_count, "large zip done")
            expected += fx.large_zip_count
        env.lib.integrity(env.check, expect_images=expected)
    return env.finish("large_uploads", api, f"{len(files)} big files ({total_mb:.0f} MB)")


async def server_restart_recovery(ctx: ScenarioContext) -> ScenarioResult:
    """SIGKILL mid-import; after restart, processing items are recovered and nothing is lost."""
    env = Env(ctx)
    check = env.check
    n = env.scale(200, 400)
    files = image_set(n, 17_000_000, folder="Crash/Pack", width=640, height=480)
    half = image_set(30, 17_100_000, folder="Crash/Half")
    async with env.client() as http:
        api = ImportClient(http, env.stats)
        main = await api.start(files, label="crash main")
        partial = await api.start(half, label="crash partial")
        await api.supply(partial, half[:15])
        await api.supply(main, files)
        before = (
            await api.wait_one(
                main.job_id,
                until=lambda j: j["counts"]["done"] >= BATCH_SIZE and j["counts"]["processing"] > 0,
                interval=0.05,
            )
        )["counts"]

    t = time.monotonic()
    ctx.server.restart(kill=True)
    ctx.server.wait_for_clip()
    t_restart = time.monotonic() - t

    async with env.client() as http:
        api = ImportClient(http, env.stats)
        after_restart = await api.job(main.job_id)
        check(after_restart["counts"]["done"] >= before["done"], "done items lost in the crash")
        await api.supply(partial, half[15:])  # the other client carries on
        final = await api.wait([main.job_id, partial.job_id])
        m, p = final[main.job_id]["counts"], final[partial.job_id]["counts"]
        check.eq(
            (final[main.job_id]["status"], m["done"], m["failed"]), ("completed", n, 0), "main job"
        )
        check.eq((final[partial.job_id]["status"], p["done"]), ("completed", 30), "partial job")
        retried = [i for i in await api.items(main.job_id) if i["attempts"] > 1]
        check(retried, "no item shows a second attempt (were any in flight at the kill?)")
        check.note(
            f"killed at done={before['done']} processing={before['processing']}; "
            f"restart+model {t_restart:.1f}s; {len(retried)} items re-claimed"
        )
        env.lib.integrity(check, expect_images=n + 30)
    return env.finish("server_restart_recovery", api, "crash recovered with no loss")


async def maintenance_during_import(ctx: ScenarioContext) -> ScenarioResult:
    """Scheduled maintenance (it runs 60 s after a fresh start) must not disturb a slow upload."""
    env = Env(ctx)
    check = env.check
    n = 40
    files = image_set(n, 18_000_000, folder="Slow/Pack")
    log = ctx.server.log_path
    tasks = ("ingest_maintenance", "sweep_orphaned_store_files", "reconcile_vectors")

    def maintenance_done() -> bool:
        text = log.read_text(errors="replace")
        return all(f"Scheduled task {t} completed" in text for t in tasks)

    async with env.client() as http:
        api = ImportClient(http, env.stats)
        started = await api.start(files, label="slow upload")
        deadline = time.monotonic() + 150
        sent = 0
        # Trickle half the files until maintenance has run, then the rest.
        while not maintenance_done() and time.monotonic() < deadline:
            if sent < n // 2:
                await api.supply(started, files[sent : sent + 1])
                sent += 1
            await asyncio.sleep(2)
        check(maintenance_done(), "maintenance tasks did not all complete within 150 s")
        mid = await api.job(started.job_id)
        check.eq(mid["counts"]["skipped"], 0, "items skipped by maintenance")
        check.eq(mid["status"], "active", "status during upload")
        await api.supply(started, files[sent:])
        job = await api.wait_one(started.job_id)
        check.eq((job["status"], job["counts"]["done"]), ("completed", n), "final")
        env.lib.integrity(check, expect_images=n)
    return env.finish("maintenance_during_import", api, "maintenance left the import alone")


@dataclass(frozen=True)
class Scenario:
    name: str
    fn: Callable[[ScenarioContext], Awaitable[ScenarioResult]]
    default_time: str
    quick_time: str
    summary: str


SCENARIO_REGISTRY: list[Scenario] = [
    Scenario("happy_path", happy_path, "~1 min", "~20s", "one import, throughput"),
    Scenario("large_manifest", large_manifest, "~1 min", "~30s", "10k-item chunked manifest"),
    Scenario("concurrent_imports", concurrent_imports, "~1 min", "~20s", "many jobs at once"),
    Scenario(
        "round_robin_fairness", round_robin_fairness, "~1 min", "~40s", "small jobs not starved"
    ),
    Scenario("endpoint_spam", endpoint_spam, "~30s", "~15s", "concurrent identical requests"),
    Scenario("cancellation_chaos", cancellation_chaos, "~1 min", "~30s", "cancel at each stage"),
    Scenario("pause_resume", pause_resume, "~1 min", "~30s", "pause holds, resume completes"),
    Scenario("reimport_duplicates", reimport_duplicates, "~30s", "~30s", "dedup tiers"),
    Scenario("import_as_copy", import_as_copy, "~30s", "~30s", "independent copies"),
    Scenario("undo_import", undo_import, "~1 min", "~40s", "DELETE removes the job's work"),
    Scenario("retry_failed", retry_failed, "~20s", "~20s", "retry with/without staged bytes"),
    Scenario(
        "interrupted_upload_resume",
        interrupted_upload_resume,
        "~20s",
        "~20s",
        "resume + finish-upload",
    ),
    Scenario("zip_archives", zip_archives, "~30s", "~30s", "archive expansion and guards"),
    Scenario("malformed_input", malformed_input, "~30s", "~30s", "corrupt files fail alone"),
    Scenario("duplicate_hash_race", duplicate_hash_race, "~20s", "~15s", "same bytes, many jobs"),
    Scenario("concurrent_move_groups", concurrent_move_groups, "~20s", "~20s", "group move race"),
    Scenario("large_uploads", large_uploads, "~1 min", "~1 min", "big files streamed"),
    Scenario(
        "server_restart_recovery", server_restart_recovery, "~1 min", "~1 min", "SIGKILL mid-import"
    ),
    Scenario(
        "maintenance_during_import",
        maintenance_during_import,
        "~2 min",
        "~2 min",
        "scheduler vs slow upload",
    ),
]
