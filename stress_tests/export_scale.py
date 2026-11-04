"""Export and rebuild at scale: time, size and peak memory of each stage, on a synthetic
library (design/export-backup-move.md §9).

Builds a library of N images in a fresh folder: the database from ``library_scale``
(groups of ~7, 4 tags and 5 colours per image), a search vector per image for the chosen
model, and a placeholder file in the store per image. Then runs, each stage in its own
process so its peak memory is its own:

1. ``export``: Export metadata (``metadata_export.export_metadata``)
2. ``check``: the rebuild's check of that export against the library
3. ``build``: building the new library alongside the live one
4. ``swap``: the swap a restart does (``swap_if_pending``)
5. ``set_aside``: setting aside files the export doesn't have (none here)

and checks the rebuilt library has every image, group and vector.

    uv run python -m stress_tests.export_scale --dir /tmp/scale --images 200000

The folder is deleted first. The placeholder files are a few bytes, so this measures the
metadata and vectors, not copying images: the full library export and Move are bound by
the disk, not this code. Times are this machine's disk; a USB drive or HDD differs.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

STAGES = ["export", "check", "build", "swap", "set_aside"]
EXPORT_NAME = "scale-export.jsonl.gz"


def _env(folder: Path, model: str) -> dict[str, str]:
    return {
        **os.environ,
        "SCENE_ATLAS_DATA_DIR": str(folder / "app-data"),
        "SCENE_ATLAS_IMAGES_DIR": str(folder / "store"),
        "SCENE_ATLAS_EMBEDDING_MODEL": model,
    }


def _peak_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1024 / 1024 if sys.platform == "darwin" else peak / 1024  # bytes vs KB


def _du(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


# ── Run inside a stage's own process (the env above already applied) ────────


def _make(n: int) -> dict:
    """The synthetic library: database, vectors, store files."""
    import numpy as np

    from backend.app.config import settings
    from backend.app.library_identity import LIBRARY_ID_KEY
    from backend.app.services import get_image_store
    from backend.app.services.lancedb_service import get_lancedb_service

    from .library_scale import build

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    db_path = settings.data_dir / "battlemap.db"
    build(db_path, n)

    import sqlite3

    con = sqlite3.connect(db_path)
    ids = [g for (g,) in con.execute("SELECT id FROM variant_groups")]
    con.executemany(
        "UPDATE variant_groups SET uid = ? WHERE id = ?", [(uuid.uuid4().hex, g) for g in ids]
    )
    con.execute(
        "UPDATE variant_groups SET image_count = "
        "(SELECT COUNT(*) FROM images WHERE variant_group_id = variant_groups.id)"
    )
    con.execute(
        "INSERT OR REPLACE INTO app_settings (key, value_json) VALUES (?, ?)",
        (LIBRARY_ID_KEY, json.dumps(str(uuid.uuid4()))),
    )
    keys = [k for (k,) in con.execute("SELECT storage_key FROM images ORDER BY id")]
    con.commit()
    con.close()

    store = get_image_store()
    for key in keys:
        store.put_bytes(key, b"x")

    # An installed model, as far as the export and rebuild look: its encoder's hash, which
    # an export records and a rebuild matches to keep the vectors (no model files needed)
    from backend.app.services.clip_service import get_effective_model_name
    from backend.app.services.model_download_service import get_model_dir

    model_dir = get_model_dir(get_effective_model_name())
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "version.json").write_text(json.dumps({"vision_sha256": "0" * 64}))

    svc = get_lancedb_service()
    svc.ensure_collection()
    rng = np.random.default_rng(1)
    batch = 5000
    for start in range(1, n + 1, batch):
        stop = min(start + batch, n + 1)
        vectors = rng.standard_normal((stop - start, svc.vector_size), dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        items = [
            {
                "image_id": i,
                "embedding": vectors[i - start].tolist(),
                "metadata": {"filename": f"f{i}.jpg", "author": ""},
            }
            for i in range(start, stop)
        ]
        if not svc.batch_add_embeddings(items):
            raise RuntimeError("adding vectors failed")
    return {"images": n, "groups": len(ids), "vector_dim": svc.vector_size}


def _stage(name: str, folder: Path) -> dict:
    from backend.pipeline import library_rebuild as lr
    from backend.pipeline import metadata_export as me
    from backend.pipeline.db import pipeline_db

    export = folder / EXPORT_NAME
    if name == "export":
        result = me.export_metadata(export)
        lr.staged_path().parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(export, lr.staged_path())
        return {"images": result["images"], "bytes": result["bytes"]}
    if name == "check":
        with pipeline_db() as db:
            check = lr.check(db)
        return {
            "images": check.images,
            "missing": check.missing["images"],
            "lost": check.lost["images"],
            "reembed": check.reembed,
        }
    if name == "build":
        with pipeline_db() as db:
            result = lr.build(db)
        lr.request_swap()
        return {k: result[k] for k in ("images", "left_out") if k in result}
    if name == "swap":
        return {"swapped": lr.swap_if_pending()}
    if name == "set_aside":
        summary = lr.set_aside()
        return {"moved": summary["moved"]}
    raise ValueError(name)


def _verify(n: int) -> dict:
    """The rebuilt library has every image, group and vector."""
    import sqlite3

    from backend.app.config import settings
    from backend.app.services.lancedb_service import get_lancedb_service

    con = sqlite3.connect(settings.data_dir / "battlemap.db")
    images = con.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    groups = con.execute("SELECT COUNT(*) FROM variant_groups").fetchone()[0]
    tags = con.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    con.close()
    vectors = len(get_lancedb_service().get_all_ids())
    ok = images == n and vectors == n and tags == 4 * n
    return {"images": images, "groups": groups, "tags": tags, "vectors": vectors, "ok": ok}


def _child(argv: list[str]) -> None:
    """``_child <make|verify|stage name> <folder> <n>``: print one JSON line."""
    what, folder, n = argv[0], Path(argv[-2]), int(argv[-1])
    started = time.perf_counter()
    if what == "make":
        result = _make(n)
    elif what == "verify":
        result = _verify(n)
    else:
        result = _stage(argv[1], folder)
    result["seconds"] = round(time.perf_counter() - started, 1)
    result["peak_mb"] = round(_peak_mb())
    print("RESULT " + json.dumps(result), flush=True)


# ── The driver ───────────────────────────────────────────────────────────────


def _run(args: list[str], env: dict[str, str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "stress_tests.export_scale", "_child", *args],
        env=env,
        capture_output=True,
        text=True,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    if proc.returncode != 0 or not lines:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit(f"{' '.join(args)} failed (exit {proc.returncode})")
    return json.loads(lines[-1].removeprefix("RESULT "))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export and rebuild at scale")
    parser.add_argument("--dir", type=Path, required=True, help="deleted first")
    parser.add_argument("--images", type=int, default=200_000)
    parser.add_argument("--model", default="large", help="small, medium or large")
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args()

    folder: Path = args.dir.resolve()
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    env = _env(folder, args.model)
    n = str(args.images)
    results: dict[str, dict] = {}

    print(f"Building a library of {args.images:,} images ({args.model} model) in {folder}")
    results["make"] = _run(["make", str(folder), n], env)
    sizes = {
        "database_bytes": (folder / "app-data" / "battlemap.db").stat().st_size,
        "vectors_bytes": _du(folder / "app-data" / "lancedb"),
    }
    print(f"  {results['make']}  {sizes}")
    for stage in STAGES:
        results[stage] = _run(["stage", stage, str(folder), n], env)
        print(f"{stage:>10}: {results[stage]}")
    results["verify"] = _run(["verify", str(folder), n], env)
    results["sizes"] = sizes
    print(f"{'verify':>10}: {results['verify']}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
    if not results["verify"]["ok"]:
        raise SystemExit("The rebuilt library is missing images, tags or vectors")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_child":
        _child(sys.argv[2:])
    else:
        main()
