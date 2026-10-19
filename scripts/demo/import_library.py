"""Import the demo library into a running Scene Atlas, for README and docs screenshots.

Follows the same import API as e2e/helpers/seed.ts: create a job, send the manifest,
seal it, send hashes, upload the files still wanted, then wait for processing.

The maps are not in the repo (see design/brand.md, Screenshots). Expected layout:

    <maps dir>/Moonlight Maps/<map>/VTT/*.jpg     (the 72 dpi copies; MA/ is skipped)
    <maps dir>/Fantasy Atlas/<map>/*.jpg
    <paintings dir>/scenes/*.jpg, <paintings dir>/portraits/*.jpg   (download_paintings.py)

Usage:
    uv run python -m scripts.demo.import_library http://127.0.0.1:8123 demo_maps <paintings dir>
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import httpx

MANIFEST_CHUNK = 2000


def collect(maps: Path, paintings: Path) -> list[tuple[Path, str, str]]:
    """(file on disk, path reported to the server, image type) for every file to import.

    The reported path drops the VTT folder so groups are named after the map.
    """
    files: list[tuple[Path, str, str]] = []
    for f in sorted((maps / "Moonlight Maps").glob("*/VTT/*.jpg")):
        files.append((f, f"Moonlight Maps/{f.parent.parent.name}/{f.name}", "battlemap"))
    for f in sorted((maps / "Fantasy Atlas").glob("*/*.jpg")):
        files.append((f, f"Fantasy Atlas/{f.parent.name}/{f.name}", "battlemap"))
    for kind in ("scenes", "portraits"):
        for f in sorted((paintings / kind).glob("*.jpg")):
            files.append((f, f"{kind.title()}/{f.name}", "scene"))
    # macOS zips add "._name.jpg" resource-fork files that aren't images
    return [x for x in files if not x[0].name.startswith("._")]


def import_files(client: httpx.Client, files: list[tuple[Path, str, str]]) -> dict:
    job = client.post(
        "/api/v1/imports", json={"label": "Demo library", "default_image_type": "battlemap"}
    )
    job.raise_for_status()
    base = f"/api/v1/imports/{job.json()['id']}"

    on_disk: dict[str, Path] = {}
    manifest = []
    for i, (path, reported, image_type) in enumerate(files):
        on_disk[str(i)] = path
        stat = path.stat()
        manifest.append(
            {
                "client_ref": str(i),
                "relative_path": reported,
                "size": stat.st_size,
                "last_modified": int(stat.st_mtime * 1000),
                "image_type": image_type,
            }
        )
    items = []
    for i in range(0, len(manifest), MANIFEST_CHUNK):
        res = client.post(f"{base}/manifest", json={"files": manifest[i : i + MANIFEST_CHUNK]})
        res.raise_for_status()
        items += res.json()["items"]
    client.post(f"{base}/seal").raise_for_status()

    # Hashes first, so files already in the library are skipped without uploading them
    waiting = [it for it in items if it["state"] == "awaiting_bytes"]
    hashes = [
        {
            "item_id": it["item_id"],
            "sha256": hashlib.sha256(on_disk[it["client_ref"]].read_bytes()).hexdigest(),
        }
        for it in waiting
    ]
    res = client.post(f"{base}/hashes", json={"items": hashes})
    res.raise_for_status()
    wanted = {r["item_id"] for r in res.json()["items"] if r["state"] == "awaiting_bytes"}
    for it in waiting:
        if it["item_id"] in wanted:
            client.put(
                f"{base}/items/{it['item_id']}/content",
                content=on_disk[it["client_ref"]].read_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            ).raise_for_status()
    print(f"Uploaded {len(wanted)} of {len(files)} files; waiting for processing")

    while True:
        detail = client.get(base).json()
        if detail["status"] in ("completed", "cancelled"):
            return detail
        time.sleep(5)


def main() -> None:
    server, maps, paintings = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    files = collect(maps, paintings)
    with httpx.Client(base_url=server, timeout=300) as client:
        detail = import_files(client, files)
    c = detail["counts"]
    print(
        f"Import {detail['status']}: {c['done']} done, {c['duplicate']} duplicate, "
        f"{c['failed']} failed, {detail['group_count']} groups"
    )


if __name__ == "__main__":
    main()
