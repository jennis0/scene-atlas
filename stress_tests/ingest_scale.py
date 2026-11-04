"""Bulk ingest at scale: wall time, throughput, peak memory and correctness of the two
ways a first-time user brings a whole library in.

1. ``local``: the desktop app's folder import (design/local-ingest.md). ``POST /imports``,
   ``POST /imports/{id}/local-sources`` with the creator folders, seal, then wait until
   the job is grouped. Then the same folders again, which must all come out duplicates.
2. ``linked``: the linked library (design/library-setup.md §4). The folder is configured
   with ``SCENE_ATLAS_LINKED_LIBRARY_DIR``; the server scans it at startup. Then a rescan
   with nothing changed, then one after renaming, deleting and adding 1% of the files.

Each path runs a real server (``run.StressTestServer``) on a fresh data folder, in app
mode, with the small search model copied into it. The test data are real, distinct
images under creator / map / variant names (``ingest_scale_data``), generated once per
run. While a path runs, the server's RSS is sampled every 0.5 s and, optionally,
``py-spy`` samples where its threads spend their time, which gives the stage
breakdown (hash, decode, thumbnails, grid detection, embedding, commit...).

    uv run python -m stress_tests.ingest_scale --dir /tmp/ingest --images 10000
    uv run python -m stress_tests.ingest_scale --dir /tmp/ingest --images 2000 --paths linked

The folder is deleted first; ``--keep`` leaves it for inspection. The run fails (exit 1)
when a correctness check fails; every check and number is in ``results.json``.
The local import is typed Battlemap by default (``--image-type auto`` for the dialog's
default), so every file takes the full path: grid detection and a copy into the store. A
linked scan is always Auto: the synthetic maps don't look like real ones to the image-type
head, so many are sorted out, and the checks count those separately rather than as losses.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil

from .ingest_scale_data import generate, plan
from .run import StressTestServer

API = "/api/v1"
IMPORTS = f"{API}/imports"
DEFAULT_MODEL_CACHE = Path(os.environ.get("INGEST_SCALE_MODEL_CACHE", ""))
MODEL = "small"
OWN_FILES = {"scene-atlas-library.json", ".backend.lock"}  # the store's own, not images

# py-spy stack buckets: the innermost frame whose function is named here wins.
STAGES: list[tuple[str, tuple[str, ...]]] = [
    ("listing", ("list_roots", "walk_files", "list_root")),
    ("hash (sha256)", ("file_sha256",)),
    ("validate (mime)", ("verify_media_mime",)),
    ("copy to .incoming", ("copyfile", "_store_original")),
    ("pixel hash", ("pixel_hash",)),
    ("thumbnails", ("write_thumbnails",)),
    ("phash + grouping features", ("perceptual_hash", "compute_grouping_features")),
    ("colours", ("extract_dominant_colors",)),
    ("auto-type features", ("_head_features", "image_features")),
    ("grid detection", ("_detect_grid", "detect_grid", "refresh_grid")),
    ("embedding", ("embed", "encode_images", "get_image_embeddings_batch")),
    ("auto-type sort", ("sort_auto_items", "_sort")),
    ("commit", ("commit_batch", "record_failures", "record_early_duplicates")),
    ("vector write", ("write_vectors", "batch_add_embeddings")),
    ("grouping phase", ("group_job", "compute_plan", "apply_plan", "plan_job")),
    ("decode (PIL load)", ("_image_pictures", "plan_decode", "load")),
    ("linked scan", ("scan_linked_folder", "apply_diff", "diff_files")),
    ("HTTP / polling", ("list_imports", "get_import", "_summaries", "run_endpoint_function")),
]


# ── Helpers ──────────────────────────────────────────────────────────────────


@dataclass
class Checks:
    """Correctness checks: each is recorded; any failure fails the run."""

    results: list[dict] = field(default_factory=list)

    def __call__(self, ok: bool, what: str, detail: Any = None) -> bool:
        self.results.append({"ok": bool(ok), "check": what, "detail": detail})
        mark = "ok  " if ok else "FAIL"
        print(f"      [{mark}] {what}" + (f": {detail}" if detail is not None else ""))
        return ok

    def eq(self, actual: Any, expected: Any, what: str) -> bool:
        return self(actual == expected, what, f"{actual} (expected {expected})")

    @property
    def failed(self) -> list[dict]:
        return [r for r in self.results if not r["ok"]]


class RssSampler:
    """Samples the server's RSS (and its children's) every ``interval`` seconds."""

    def __init__(self, pid: int, interval: float = 0.5) -> None:
        self.proc = psutil.Process(pid)
        self.interval = interval
        self.samples: list[tuple[float, float]] = []  # (monotonic, MB)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _rss(self) -> float:
        total = self.proc.memory_info().rss
        for child in self.proc.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                total += child.memory_info().rss
        return total / 1024 / 1024

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.samples.append((time.monotonic(), self._rss()))
            except psutil.Error:
                return
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def peak_between(self, t0: float, t1: float) -> float:
        values = [mb for t, mb in self.samples if t0 <= t <= t1]
        return round(max(values), 1) if values else 0.0

    def at(self, t: float) -> float:
        before = [mb for ts, mb in self.samples if ts <= t]
        return round(before[-1], 1) if before else 0.0


class Profiler:
    """``py-spy record`` against the server for a window starting ``delay`` s from now, so
    it samples the steady state rather than the start; no profile if py-spy is missing."""

    def __init__(self, pid: int, out: Path, seconds: int, delay: float = 60) -> None:
        self.out = out
        self.proc: subprocess.Popen | None = None
        cmd = ["py-spy"] if shutil.which("py-spy") else ["uvx", "py-spy"]
        self.cmd = [*cmd, "record", "--pid", str(pid), "--duration", str(seconds), "--rate",
                    "25", "--format", "raw", "--nonblocking", "--output", str(out)]  # fmt: skip
        self.timer = threading.Timer(delay, self._start)
        self.timer.start()

    def _start(self) -> None:
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def finish(self, timeout: float = 600) -> dict[str, float] | None:
        self.timer.cancel()
        if self.proc is None:  # the import finished before the window
            return None
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if not self.out.exists():
            err = self.proc.stderr.read().decode()[-500:] if self.proc.stderr else ""
            print(f"      py-spy gave no profile: {err}")
            return None
        return bucket_profile(self.out)


def bucket_profile(path: Path) -> dict[str, float]:
    """Share of non-idle samples per stage, from py-spy's folded stacks."""
    lookup = {name: stage for stage, names in STAGES for name in names}
    counts: collections.Counter[str] = collections.Counter()
    for line in path.read_text(errors="replace").splitlines():
        stack, _, n = line.rpartition(" ")
        if not n.isdigit():
            continue
        frames = [f.split(" (")[0].strip() for f in stack.split(";")]
        bucket = next((lookup[f] for f in reversed(frames) if f in lookup), "other")
        counts[bucket] += int(n)
    total = sum(counts.values()) or 1
    return {k: round(100 * v / total, 1) for k, v in counts.most_common()}


def du(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.lstat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def files_under(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()] if path.exists() else []


def store_files(store: Path) -> list[Path]:
    """The library folder's files, less the scheduled backup kept in it
    (``settings.backups_dir``), which can run partway through a long import."""
    return [p for p in files_under(store) if p.relative_to(store).parts[0] != "backups"]


def mb(n: int) -> float:
    return round(n / 1024 / 1024, 1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seed_model(data_dir: Path, cache: Path) -> None:
    """Copy the cached model into ``{data}/models/small`` as e2e's ``seedModel`` does."""
    target = data_dir / "models" / MODEL
    if not (cache / "version.json").exists():
        raise SystemExit(f"No cached {MODEL} model at {cache} (set --model-cache)")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cache, target, dirs_exist_ok=True)


class Server:
    """A ``StressTestServer`` with this benchmark's environment, RSS sampling and a client."""

    def __init__(self, work: Path, model_cache: Path, env: dict[str, str]) -> None:
        self.srv = StressTestServer(work)
        seed_model(self.srv.data_dir, model_cache)
        self.env = {"SCENE_ATLAS_APP_MODE": "app", "SCENE_ATLAS_EMBEDDING_MODEL": MODEL, **env}
        self.sampler: RssSampler | None = None
        self.http: httpx.Client | None = None
        self.started_at = 0.0

    def start(self) -> None:
        saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        # The model is already copied in; nothing to link
        os.environ["STRESS_MODELS_DIR"] = str(self.srv.work_dir / "no-models")
        try:
            self.started_at = time.monotonic()
            base = self.srv.start(timeout=180)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        assert self.srv._proc is not None
        self.sampler = RssSampler(self.srv._proc.pid)
        self.http = httpx.Client(base_url=base, timeout=600)

    @property
    def pid(self) -> int:
        assert self.srv._proc is not None
        return self.srv._proc.pid

    def wait_ready(self) -> float:
        """Until the model has loaded and the queue isn't system-paused; seconds taken."""
        t0 = time.monotonic()
        self.srv.wait_for_clip(timeout=600)
        return time.monotonic() - t0

    def stop(self) -> None:
        if self.sampler:
            self.sampler.stop()
        if self.http:
            self.http.close()
        self.srv.stop()

    def ok(self, method: str, path: str, **kw) -> Any:
        assert self.http is not None
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    def db(self, sql: str, args: tuple = ()) -> list[tuple]:
        con = sqlite3.connect(f"file:{self.srv.data_dir / 'battlemap.db'}?mode=ro", uri=True,
                              timeout=60)  # fmt: skip
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def scalar(self, sql: str, args: tuple = ()) -> Any:
        return self.db(sql, args)[0][0]

    def log(self) -> str:
        return self.srv.log_path.read_text(errors="replace") if self.srv.log_path.exists() else ""


@dataclass
class Timeline:
    """Polls of one job: (seconds since t0, counts, status, poll latency, RSS MB)."""

    t0: float
    rows: list[dict] = field(default_factory=list)

    def first(self, cond) -> float | None:
        return next((r["t"] for r in self.rows if cond(r)), None)


def wait_job(s: Server, job_id: str, t0: float, timeout: float, label: str) -> Timeline:
    """Poll ``GET /imports`` (the list the app's activity dock polls) until the job is
    completed (grouped), recording its counts each second."""
    tl = Timeline(t0)
    deadline = time.monotonic() + timeout
    last_print = 0.0
    last_done, last_change = -1, time.monotonic()
    assert s.http is not None
    while True:
        p0 = time.monotonic()
        r = s.http.get(IMPORTS, params={"limit": 200, "include_dismissed": True})
        latency = time.monotonic() - p0
        r.raise_for_status()
        body = r.json()
        job = next((j for j in body["jobs"] if j["id"] == job_id), None) or s.ok(
            "GET", f"{IMPORTS}/{job_id}"
        )
        c = job["counts"]
        now = time.monotonic()
        tl.rows.append(
            {
                "t": round(now - t0, 2),
                "status": job["status"],
                "counts": c,
                "poll_s": round(latency, 3),
                "rss_mb": s.sampler.at(now) if s.sampler else None,
                "queue_paused": body["queue"]["system_paused"],
                "queue_reason": body["queue"]["reason"],
            }
        )
        settled = c["done"] + c["duplicate"] + c["failed"] + c["skipped"]
        if settled != last_done:
            last_done, last_change = settled, now
        elif now - last_change > 300 and job["status"] != "grouping":
            print(f"      WARNING: {label} made no progress for 5 min: {c}")
            last_change = now
        if now - last_print > 15:
            rate = settled / max(now - t0, 1e-6)
            print(
                f"      {now - t0:7.0f}s {job['status']:<9} {settled:>6}/{c['total']} "
                f"(done {c['done']}, dup {c['duplicate']}, skip {c['skipped']}, "
                f"fail {c['failed']}) {rate:5.1f}/s  RSS {tl.rows[-1]['rss_mb']} MB  "
                f"poll {latency * 1000:.0f} ms"
            )
            last_print = now
        if job["status"] in ("completed", "cancelled"):
            return tl
        if now > deadline:
            raise TimeoutError(f"{label}: job {job_id} not finished after {timeout}s: {c}")
        time.sleep(1.0)


def summarise(tl: Timeline, n_items: int) -> dict:
    """Phase times from a timeline: processing (until every file settled), grouping."""
    rows = tl.rows
    end = rows[-1]["t"]

    def settled(r):
        c = r["counts"]
        return c["done"] + c["duplicate"] + c["failed"] + c["skipped"]

    first_done = tl.first(lambda r: settled(r) > 0)
    all_settled = tl.first(lambda r: settled(r) >= r["counts"]["total"])
    polls = [r["poll_s"] for r in rows]
    out = {
        "total_s": end,
        "first_file_settled_s": first_done,
        "all_files_settled_s": all_settled,
        "grouping_s": round(end - all_settled, 1) if all_settled is not None else None,
        "items_per_s_overall": round(n_items / end, 2) if end else None,
        "items_per_s_processing": (
            round(n_items / (all_settled - (first_done or 0)), 2)
            if all_settled and all_settled > (first_done or 0)
            else None
        ),
        "poll_ms_p50": round(1000 * sorted(polls)[len(polls) // 2], 1),
        "poll_ms_max": round(1000 * max(polls), 1),
        "system_paused_polls": sum(1 for r in rows if r["queue_paused"]),
        "pause_reasons": sorted({r["queue_reason"] for r in rows if r["queue_reason"]}),
    }
    # Throughput per tenth of the run, to see whether it slows as the library grows (only
    # for runs long enough that a tenth spans several 1 s polls)
    deciles: list[float | None] = []
    total = rows[-1]["counts"]["total"] or 1
    for k in range(1, 11 if (all_settled or 0) > 60 else 1):
        t = tl.first(lambda r, k=k: settled(r) >= total * k / 10)
        deciles.append(t)
    rates = []
    prev = first_done or 0
    for t in deciles:
        if t is None:
            break
        rates.append(round((total / 10) / max(t - prev, 1e-6), 2))
        prev = t
    out["items_per_s_by_decile"] = rates
    out["rss_mb_by_decile"] = [
        next((r["rss_mb"] for r in rows if r["t"] >= t), None) for t in deciles if t is not None
    ]
    return out


def log_errors(text: str, since: int = 0) -> dict:
    """ERROR/WARNING/Traceback lines in the server log after offset ``since``."""
    lines = text[since:].splitlines()
    errors = [ln for ln in lines if " ERROR " in ln or "Traceback" in ln or "CRITICAL" in ln]
    warnings = [ln for ln in lines if " WARNING " in ln]
    heartbeat = [ln for ln in lines if "[heartbeat]" in ln]
    common = collections.Counter(
        re.sub(r"\d+", "N", ln.split(" - ", 1)[-1])[:160] for ln in warnings
    )
    return {
        "errors": len(errors),
        "error_samples": errors[:8],
        "warnings": len(warnings),
        "warning_kinds": common.most_common(8),
        "heartbeats": len(heartbeat),
    }


# ── Library checks (shared) ──────────────────────────────────────────────────


def check_library(
    s: Server,
    checks: Checks,
    manifest: dict[str, dict],
    *,
    linked: bool,
    sorted_out_hashes: set[str],
) -> dict:
    """Every manifest file is one image exactly once (unless Auto sorted it out), with a
    thumbnail, a vector and a group; no temp files left."""
    data, store = s.srv.data_dir, s.srv.library_dir
    rows = s.db(
        "SELECT id, content_hash, thumbnail_key, storage_key, source_file_id, variant_group_id, "
        "awaiting_grouping, author, image_type FROM images"
    )
    by_hash = collections.Counter(r[1] for r in rows)
    expected = {m["sha256"] for m in manifest.values()} - sorted_out_hashes
    checks.eq(len(rows), len(expected), "image rows = files not sorted out")
    checks.eq(sum(1 for h, c in by_hash.items() if c > 1), 0, "hashes held by >1 image")
    checks.eq(len(expected - set(by_hash)), 0, "files with no image (and not sorted out)")
    checks.eq(len(set(by_hash) - expected), 0, "images that aren't any file")
    checks.eq(sum(1 for r in rows if r[6]), 0, "images still awaiting grouping (hidden)")
    checks.eq(sum(1 for r in rows if r[5] is None), 0, "images with no group")

    thumbs = {
        p.name for p in files_under(data / "store" / "thumbnails") if ".incoming" not in p.parts
    }
    checks.eq(sum(1 for r in rows if r[2] not in thumbs), 0, "images whose thumbnail is missing")
    if linked:
        checks.eq(sum(1 for r in rows if r[3] is not None), 0, "linked images with a storage_key")
        checks.eq(sum(1 for r in rows if r[4] is None), 0, "linked images with no source file")
        stored = [p for p in store_files(store) if p.name not in OWN_FILES]
        checks.eq(len(stored), 0, "files copied into the store by a linked scan")
    else:
        stored = {p.name for p in store_files(store) if ".incoming" not in p.parts}
        checks.eq(sum(1 for r in rows if r[3] not in stored), 0, "images whose original is missing")
        checks.eq(len(stored - {r[3] for r in rows} - OWN_FILES), 0,
                  "store files no image references")  # fmt: skip

    vectors = vector_ids(s)
    ids = {r[0] for r in rows}
    checks.eq(len(ids - vectors), 0, "images with no vector")
    checks.eq(len(vectors - ids), 0, "vectors with no image")

    leftovers = {
        "store/.incoming": [str(p) for p in files_under(store / ".incoming")][:5],
        "thumbnails/.incoming": [str(p) for p in files_under(data / "store" / "thumbnails" / ".incoming")][:5],
    }  # fmt: skip
    # Sorted-out items keep a preview in staging/ for 24 h (ingestion.md §5.6): not leftovers
    previews = {Path(k).name for (k,) in s.db(
        "SELECT preview_key FROM import_items WHERE preview_key IS NOT NULL")}  # fmt: skip
    staged = [p for p in files_under(data / "staging") if p.name not in previews]
    leftovers["staging"] = [str(p) for p in staged][:5]
    checks.eq(len(staged), 0, "files left in staging/ (other than sorted-out previews)")
    checks.eq(len(files_under(store / ".incoming")), 0, "files left in the store's .incoming/")
    checks.eq(len(files_under(data / "store" / "thumbnails" / ".incoming")), 0,
              "files left in thumbnails/.incoming/")  # fmt: skip

    # Grouping: each map folder should be one gallery group, and no group should mix maps
    rel_of = {m["sha256"]: rel for rel, m in manifest.items()}
    folder_groups: dict[str, set] = collections.defaultdict(set)
    group_folders: dict[int, set] = collections.defaultdict(set)
    wrong_author = 0
    wrong: collections.Counter[tuple[str, str]] = collections.Counter()
    for r in rows:
        rel = rel_of.get(r[1])
        if rel is None:
            continue
        creator, folder = rel.split("/")[0], "/".join(rel.split("/")[:2])
        folder_groups[folder].add(r[5])
        group_folders[r[5]].add(folder)
        wrong_author += r[7] != creator
        if r[7] != creator:
            wrong[(creator, r[7])] += 1
    groups = s.scalar("SELECT COUNT(*) FROM variant_groups")
    split = sum(1 for g in folder_groups.values() if len(g) > 1)
    mixed = sum(1 for f in group_folders.values() if len(f) > 1)
    types = collections.Counter(r[8] for r in rows)
    checks(groups > 0, "groups formed", groups)
    checks.eq(wrong_author, 0, "images whose author isn't their creator folder")
    return {
        "images": len(rows),
        "groups": groups,
        "map_folders": len(folder_groups),
        "map_folders_split_across_groups": split,
        "groups_mixing_map_folders": mixed,
        "image_types": dict(types),
        "wrong_authors": [[c, a, k] for (c, a), k in wrong.most_common(20)],
        "vectors": len(vectors),
        "thumbnail_files": len(thumbs),
        "leftovers": leftovers,
    }


def vector_ids(s: Server) -> set[int]:
    """Image ids in LanceDB, read by a child process with the server's settings."""
    env = {**os.environ, **s.env, "SCENE_ATLAS_DATA_DIR": str(s.srv.data_dir),
           "SCENE_ATLAS_IMAGES_DIR": str(s.srv.library_dir)}  # fmt: skip
    code = (
        "import json;from backend.app.services.lancedb_service import get_lancedb_service as g;"
        "print('IDS '+json.dumps(sorted(g().get_all_ids())))"
    )
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("IDS ")), None)
    if line is None:
        raise RuntimeError(f"Reading vectors failed: {proc.stderr[-2000:]}")
    return set(json.loads(line[4:]))


def sorted_out(s: Server, job_id: str) -> set[str]:
    """Content hashes of the job's items Auto sorted out (no image, by design)."""
    rows = s.db(
        "SELECT source_hash, source_path FROM import_items WHERE job_id = ? AND state = 'skipped'",
        (job_id,),
    )
    return {h if h else sha256_file(Path(p)) for h, p in rows}


def item_states(s: Server, job_id: str) -> dict:
    rows = s.db(
        "SELECT state, error_kind, COUNT(*) FROM import_items WHERE job_id = ? GROUP BY 1, 2",
        (job_id,),
    )
    return {f"{st}/{k}" if k else st: n for st, k, n in rows}


def failures(s: Server, job_id: str, limit: int = 10) -> list:
    return s.db(
        "SELECT relative_path, error_stage, error_reason, substr(error_detail, 1, 200) "
        "FROM import_items WHERE job_id = ? AND state = 'failed' LIMIT ?",
        (job_id, limit),
    )


# ── Path 1: local folder import ──────────────────────────────────────────────


def run_local(args, dataset: Path, manifest: dict[str, dict], work: Path, out: Path) -> dict:
    checks = Checks()
    res: dict[str, Any] = {"checks": checks.results}
    s = Server(work, args.model_cache, {})
    s.start()
    try:
        res["model_ready_s"] = round(s.wait_ready(), 1)
        roots = sorted(str(p) for p in dataset.iterdir() if p.is_dir())
        n = len(manifest)

        def one_import(label: str, profile: bool) -> tuple[str, dict]:
            t0 = time.monotonic()
            job_id = s.ok(
                "POST", IMPORTS, json={"label": label, "default_image_type": args.image_type}
            )["id"]
            t = time.monotonic()
            counts = s.ok("POST", f"{IMPORTS}/{job_id}/local-sources", json={"paths": roots})
            listed = time.monotonic() - t
            t = time.monotonic()
            s.ok("POST", f"{IMPORTS}/{job_id}/seal", timeout=900)
            sealed = time.monotonic() - t
            prof = (
                Profiler(s.pid, out / f"{label}.pyspy.txt", args.profile_seconds)
                if profile
                else None
            )
            tl = wait_job(s, job_id, t0, args.timeout, label)
            t1 = time.monotonic()
            r = {
                "local_sources_s": round(listed, 2),
                "local_sources_counts": counts,
                "seal_s": round(sealed, 2),
                **summarise(tl, n),
                "peak_rss_mb": s.sampler.peak_between(t0, t1) if s.sampler else None,
                "final_counts": tl.rows[-1]["counts"],
                "item_states": item_states(s, job_id),
                "failures_sample": failures(s, job_id),
            }
            if prof:
                r["profile_pct"] = prof.finish()
            (out / f"{label}.timeline.json").write_text(json.dumps(tl.rows))
            return job_id, r

        log0 = len(s.log())
        print("    first import")
        job1, first = one_import("local-first", args.profile_seconds > 0)
        res["first"] = first
        c = first["final_counts"]
        checks.eq(c["total"], n, "items listed = files")
        checks.eq(c["failed"], 0, "failed items")
        checks.eq(c["duplicate"], 0, "duplicates in a folder of distinct files")
        checks.eq(c["done"] + c["skipped"], n, "done + sorted out = files")
        checks.eq(c["skipped"], c["sorted_out"], "skips are all Auto sort-outs")
        out_hashes = sorted_out(s, job1)
        res["first"]["library"] = check_library(s, checks, manifest, linked=False,
                                                sorted_out_hashes=out_hashes)  # fmt: skip
        res["first"]["log"] = log_errors(s.log(), log0)
        disk = {"data_dir_mb": mb(du(s.srv.data_dir)), "store_mb": mb(du(s.srv.library_dir)),
                "thumbnails_mb": mb(du(s.srv.data_dir / "store" / "thumbnails")),
                "lancedb_mb": mb(du(s.srv.data_dir / "lancedb")),
                "db_mb": mb((s.srv.data_dir / "battlemap.db").stat().st_size)}  # fmt: skip
        res["disk"] = disk
        images_before = s.scalar("SELECT COUNT(*) FROM images")
        store_before = len(store_files(s.srv.library_dir))
        max_id_before = s.scalar("SELECT MAX(id) FROM images")

        print("    re-import of the same folders")
        log1 = len(s.log())
        job2, again = one_import("local-again", False)
        res["again"] = again
        c = again["final_counts"]
        checks.eq(c["duplicate"], images_before, "re-import: every imported file is a duplicate")
        checks.eq(c["done"], 0, "re-import: nothing imported")
        checks.eq(c["failed"], 0, "re-import: failed items")
        checks.eq(s.scalar("SELECT COUNT(*) FROM images"), images_before, "re-import: image rows")
        checks.eq(s.scalar("SELECT MAX(id) FROM images"), max_id_before, "re-import: no new ids")
        checks.eq(len(store_files(s.srv.library_dir)), store_before, "re-import: store files")
        tiers = dict(s.db("SELECT duplicate_tier, COUNT(*) FROM import_items WHERE job_id = ? "
                          "AND state = 'duplicate' GROUP BY 1", (job2,)))  # fmt: skip
        again["duplicate_tiers"] = tiers
        res["again"]["log"] = log_errors(s.log(), log1)
        return res
    finally:
        s.stop()
        shutil.copy(s.srv.log_path, out / "local-server.log")


# ── Path 2: linked library ───────────────────────────────────────────────────


def linked_job_ids(s: Server) -> list[str]:
    jobs = s.ok("GET", IMPORTS, params={"limit": 200, "include_dismissed": True})["jobs"]
    return [j["id"] for j in jobs if j.get("linked")]


def wait_scan(s: Server, previous: str | None, timeout: float = 600) -> tuple[float, dict]:
    """Until ``/library/status`` says no scan is running and ``last_scan_at`` moved."""
    t0 = time.monotonic()
    while True:
        st = s.ok("GET", f"{API}/library/status")["linked"]
        if not st["scanning"] and st["last_scan_at"] and st["last_scan_at"] != previous:
            return time.monotonic() - t0, st
        if time.monotonic() - t0 > timeout:
            raise TimeoutError(f"scan didn't finish: {st}")
        time.sleep(0.1)


def scan_log_lines(text: str) -> list[str]:
    return [ln.split(" - ", 1)[-1] for ln in text.splitlines() if "Linked scan of" in ln]


def wait_linked_job(s: Server, known: set[str], t0: float, timeout: float, label: str):
    """The scan's job (one not in ``known``) to completion; None if no job appears."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        new = [j for j in linked_job_ids(s) if j not in known]
        if new:
            return new[0], wait_job(s, new[0], t0, timeout, label)
        st = s.ok("GET", f"{API}/library/status")["linked"]
        if st and not st["scanning"] and st["last_scan_at"]:
            new = [j for j in linked_job_ids(s) if j not in known]
            return (new[0], wait_job(s, new[0], t0, timeout, label)) if new else (None, None)
        time.sleep(0.5)
    return None, None


def source_rows(s: Server) -> dict[str, tuple]:
    rows = s.db(
        "SELECT rel_key, state, image_id, content_hash, missing_since, id FROM source_files"
    )
    return {r[0]: r[1:] for r in rows}


def run_linked(args, dataset: Path, manifest: dict[str, dict], work: Path, out: Path) -> dict:
    checks = Checks()
    res: dict[str, Any] = {"checks": checks.results}
    s = Server(work, args.model_cache, {"SCENE_ATLAS_LINKED_LIBRARY_DIR": str(dataset)})
    n = len(manifest)
    t0 = time.monotonic()
    s.start()
    try:
        # The startup scan runs while the model loads; its items wait for the model
        print("    first scan (at startup)")
        prof = (
            Profiler(s.pid, out / "linked-first.pyspy.txt", args.profile_seconds)
            if args.profile_seconds
            else None
        )
        job1, tl = wait_linked_job(s, set(), t0, args.timeout, "linked-first")
        t1 = time.monotonic()
        if job1 is None:
            checks(False, "first scan created a job")
            return res
        assert tl is not None  # set whenever the job is
        first = {
            "server_start_s": round(s.started_at - t0, 1),
            **summarise(tl, n),
            "peak_rss_mb": s.sampler.peak_between(t0, t1) if s.sampler else None,
            "final_counts": tl.rows[-1]["counts"],
            "item_states": item_states(s, job1),
            "failures_sample": failures(s, job1),
            "scan_log": scan_log_lines(s.log()),
        }
        if prof:
            first["profile_pct"] = prof.finish()
        (out / "linked-first.timeline.json").write_text(json.dumps(tl.rows))
        res["first"] = first
        c = first["final_counts"]
        checks.eq(c["total"], n, "items queued = files")
        checks.eq(c["failed"], 0, "failed items")
        checks.eq(c["duplicate"], 0, "duplicates in a folder of distinct files")
        checks.eq(c["done"] + c["skipped"], n, "done + sorted out = files")
        out_hashes = sorted_out(s, job1)
        first["library"] = check_library(
            s, checks, manifest, linked=True, sorted_out_hashes=out_hashes
        )
        rows = source_rows(s)
        states = collections.Counter(r[0] for r in rows.values())
        first["source_file_states"] = dict(states)
        checks.eq(len(rows), n, "source_files rows = files")
        checks.eq(states.get("pending", 0), 0, "source_files still pending")
        first["log"] = log_errors(s.log())
        res["disk"] = {"data_dir_mb": mb(du(s.srv.data_dir)), "store_mb": mb(du(s.srv.library_dir)),
                       "thumbnails_mb": mb(du(s.srv.data_dir / "store" / "thumbnails")),
                       "lancedb_mb": mb(du(s.srv.data_dir / "lancedb")),
                       "db_mb": mb((s.srv.data_dir / "battlemap.db").stat().st_size)}  # fmt: skip

        # Rescan, nothing changed
        print("    rescan, nothing changed")
        before_jobs = set(linked_job_ids(s))
        last = s.ok("GET", f"{API}/library/status")["linked"]["last_scan_at"]
        log0 = len(s.log())
        tr = time.monotonic()
        started = s.ok("POST", f"{API}/library/scan", json={"reason": "manual"})["started"]
        took, st = wait_scan(s, last)
        res["rescan_unchanged"] = {
            "started": started,
            "seconds": round(time.monotonic() - tr, 2),
            "scan_log": scan_log_lines(s.log()[log0:]),
            "peak_rss_mb": s.sampler.peak_between(tr, time.monotonic()) if s.sampler else None,
        }
        print(f"      {res['rescan_unchanged']}")
        checks(started, "unchanged rescan started")
        checks.eq(set(linked_job_ids(s)) - before_jobs, set(), "unchanged rescan created a job")
        checks.eq(st["missing_count"], 0, "missing after an unchanged rescan")

        # Rename 1%, delete 1%, add 1%
        print("    rescan after renaming, deleting and adding 1% each")
        rows = source_rows(s)
        imaged = sorted(k for k, r in rows.items() if r[0] == "image")
        rng = random.Random(args.seed)
        k = max(1, n // 100)
        picks = rng.sample(imaged, 2 * k)
        renamed, deleted = picks[:k], picks[k:]
        rename_map: dict[str, str] = {}
        image_of = {rel: rows[rel][1] for rel in picks}
        # Give the renamed images an edited name, which a move must keep
        for rel in renamed:
            s.ok("PATCH", f"{API}/images/{image_of[rel]}", json={"name": f"Edited {image_of[rel]}"})
        group_of = dict(s.db("SELECT id, variant_group_id FROM images"))
        for i, rel in enumerate(renamed):
            src = dataset / rel
            if i % 2:  # into another folder of the same creator
                dst = src.parent.parent / "Moved Here" / f"moved_{src.name}"
            else:
                dst = src.with_name(f"{src.stem} (renamed){src.suffix}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            rename_map[rel] = dst.relative_to(dataset).as_posix()
        for rel in deleted:
            (dataset / rel).unlink()
        added = generate(dataset, plan(k, seed=args.seed, start=n + 1), workers=os.cpu_count())
        added_hashes = {a["sha256"] for a in added}
        images_before = s.scalar("SELECT COUNT(*) FROM images")

        last = s.ok("GET", f"{API}/library/status")["linked"]["last_scan_at"]
        before_jobs = set(linked_job_ids(s))
        log0 = len(s.log())
        tr = time.monotonic()
        s.ok("POST", f"{API}/library/scan", json={"reason": "manual"})
        scan_s, _ = wait_scan(s, last)
        job3, tl3 = wait_linked_job(s, before_jobs, tr, args.timeout, "linked-changes")
        t3 = time.monotonic()
        ch: dict[str, Any] = {
            "scan_s": round(scan_s, 2),
            "scan_log": scan_log_lines(s.log()[log0:]),
            "renamed": k,
            "deleted": k,
            "added": k,
        }
        res["rescan_changes"] = ch
        if job3 is None:
            checks(False, "changes rescan created a job")
        else:
            assert tl3 is not None  # set whenever the job is
            ch.update(summarise(tl3, len(added) + len(renamed)))
            ch["final_counts"] = tl3.rows[-1]["counts"]
            ch["item_states"] = item_states(s, job3)
            ch["failures_sample"] = failures(s, job3)
            ch["peak_rss_mb"] = s.sampler.peak_between(tr, t3) if s.sampler else None
        rows = source_rows(s)
        img = {
            r[0]: r[1:] for r in s.db("SELECT id, name, variant_group_id, content_hash FROM images")
        }
        kept = sum(1 for old, new in rename_map.items()
                   if new in rows and rows[new][1] == image_of[old] and rows[new][0] == "image")  # fmt: skip
        checks.eq(kept, k, "renamed files kept their image id")
        checks.eq(sum(1 for old in rename_map if old in rows), 0, "old rows of renamed files left")
        named = sum(
            1 for old in renamed if img.get(image_of[old], (None,))[0] == f"Edited {image_of[old]}"
        )
        checks.eq(named, k, "renamed images kept their edited name")
        same_group = sum(
            1
            for old in renamed
            if img.get(image_of[old], (None, None))[1] == group_of[image_of[old]]
        )
        checks.eq(same_group, k, "renamed images kept their group")
        checks.eq(sum(1 for new in rename_map.values() if rows.get(new, (None,) * 4)[3] is not None),
                  0, "renamed files marked missing")  # fmt: skip
        missing = sum(1 for rel in deleted if rel in rows and rows[rel][3] is not None)
        checks.eq(missing, k, "deleted files marked missing (image kept)")
        checks.eq(
            sum(1 for rel in deleted if image_of[rel] in img), k, "images of deleted files kept"
        )
        st = s.ok("GET", f"{API}/library/status")["linked"]
        checks.eq(st["missing_count"], k, "status missing_count")
        new_out = sorted_out(s, job3) if job3 else set()
        have = {r[2] for r in img.values()}
        added_imported = len(added_hashes - new_out)
        checks.eq(len((added_hashes - new_out) - have), 0, "added files not imported")
        checks.eq(s.scalar("SELECT COUNT(*) FROM images"), images_before + added_imported,
                  "image rows after changes")  # fmt: skip
        by_hash = collections.Counter(r[2] for r in img.values())
        checks.eq(sum(1 for c in by_hash.values() if c > 1), 0, "hashes held by >1 image (after)")
        previews = {Path(k).name for (k,) in s.db(
            "SELECT preview_key FROM import_items WHERE preview_key IS NOT NULL")}  # fmt: skip
        staged = [p for p in files_under(s.srv.data_dir / "staging") if p.name not in previews]
        checks.eq(len(staged), 0, "files left in staging/ (after, other than previews)")
        vectors = vector_ids(s)
        checks.eq(len(set(img) - vectors), 0, "images with no vector (after)")
        checks.eq(sum(1 for r in s.db("SELECT awaiting_grouping, variant_group_id FROM images")
                      if r[0] or r[1] is None), 0, "images hidden or ungrouped (after)")  # fmt: skip
        ch["source_file_states"] = dict(collections.Counter(r[0] for r in rows.values()))
        ch["log"] = log_errors(s.log(), log0)

        # One more unchanged rescan: the changed state should now be stable
        last = s.ok("GET", f"{API}/library/status")["linked"]["last_scan_at"]
        before_jobs = set(linked_job_ids(s))
        log0 = len(s.log())
        tr = time.monotonic()
        s.ok("POST", f"{API}/library/scan", json={"reason": "manual"})
        wait_scan(s, last)
        res["rescan_after_changes"] = {"seconds": round(time.monotonic() - tr, 2),
                                       "scan_log": scan_log_lines(s.log()[log0:])}  # fmt: skip
        checks.eq(
            set(linked_job_ids(s)) - before_jobs, set(), "second unchanged rescan created a job"
        )
        res["log"] = log_errors(s.log())
        return res
    finally:
        s.stop()
        shutil.copy(s.srv.log_path, out / "linked-server.log")


# ── Driver ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk ingest at scale")
    parser.add_argument("--dir", type=Path, required=True, help="work folder (deleted first)")
    parser.add_argument("--images", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--paths", default="local,linked", help="local, linked or both")
    parser.add_argument("--image-type", default="battlemap", choices=["auto", "battlemap", "scene"],
                        help="the local import's type (the linked scan is always Auto)")  # fmt: skip
    parser.add_argument("--model-cache", type=Path, default=DEFAULT_MODEL_CACHE,
                        help="a folder holding the small model (version.json, *.onnx)")  # fmt: skip
    parser.add_argument("--timeout", type=float, default=4 * 3600, help="per import, seconds")
    parser.add_argument("--profile-seconds", type=int, default=90,
                        help="py-spy window during each first import (0 = off)")  # fmt: skip
    parser.add_argument("--keep", action="store_true", help="keep the generated data")
    args = parser.parse_args()

    folder: Path = args.dir.resolve()
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    out = folder / "results"
    out.mkdir()
    results: dict[str, Any] = {"images": args.images, "image_type": args.image_type,
                               "cpus": os.cpu_count(),
                               "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)}  # fmt: skip
    dataset = folder / "Battle Maps"
    print(f"Generating {args.images:,} images in {dataset}")
    t = time.monotonic()
    generated = generate(dataset, plan(args.images, seed=args.seed))
    results["generate_s"] = round(time.monotonic() - t, 1)
    manifest = {g["rel"]: g for g in generated}
    if len({g["sha256"] for g in generated}) != len(generated):
        raise SystemExit("Generated files aren't distinct")
    results["dataset_mb"] = mb(du(dataset))
    results["map_folders"] = len({"/".join(r.split("/")[:2]) for r in manifest})
    print(
        f"  {results['generate_s']} s, {results['dataset_mb']} MB, {results['map_folders']} map folders"
    )
    digest = {rel: m["sha256"] for rel, m in manifest.items()}

    failed: list[str] = []
    try:
        for path in [p.strip() for p in args.paths.split(",") if p.strip()]:
            print(f"\n== {path} ==")
            work = folder / f"work-{path}"
            run = run_local if path == "local" else run_linked
            res = run(args, dataset, manifest, work, out)
            results[path] = res
            failed += [
                f"{path}: {c['check']} ({c['detail']})" for c in res["checks"] if not c["ok"]
            ]
            if path == "local":
                # The source folder is never written
                changed = sum(1 for rel, h in digest.items() if sha256_file(dataset / rel) != h)
                res["source_files_changed"] = changed
                if changed:
                    failed.append(f"local: {changed} source files changed")
            (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
            if not args.keep:
                shutil.rmtree(work, ignore_errors=True)
    finally:
        (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
        print(f"\nResults: {out / 'results.json'}")
        if not args.keep:
            shutil.rmtree(dataset, ignore_errors=True)
    if failed:
        print("\nFAILED checks:\n  " + "\n  ".join(failed))
        raise SystemExit(1)
    print("\nAll checks passed")


if __name__ == "__main__":
    main()
