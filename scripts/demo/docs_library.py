"""Lay out the demo library for the docs screenshots (design/brand.md, Screenshots).

From the demo maps folder, builds under <work dir>:

    import/   Moonlight Maps and 2 Minute Tabletop, minus the held-back packs (symlinks),
              for import_library.py
    held/2 Minute Tabletop/<pack>/   two packs with tokens (copies), imported through the
              UI by the screenshot run so the import dialog and its report are real
    linked/My Maps/Fantasy Atlas/<map>/*.jpg   copies: the linked folder (SCENE_ATLAS_LINKED_LIBRARY_DIR).
              Copies, because the linked scan skips symlinks
    data/models/<name>   symlinks to downloaded models (default: the repo's data/models;
              a worktree passes its main checkout's), so nothing is downloaded

Then, against the server started on those folders, `setup` adds the Fantasy tag pack and
finishes first-run setup, as the wizard would.

Usage:
    uv run python -m scripts.demo.docs_library layout demo_maps /tmp/docs-demo [models dir]
    uv run python -m scripts.demo.docs_library setup http://127.0.0.1:8123
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TABLETOP = "2 Minute Tabletop"
# Their Tokens folders give the import report real "skipped by Auto" rows
HELD = ("Ancient Chamber", "Deephollow Depths")


def _link(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(target.resolve(), target_is_directory=target.is_dir())


def layout(maps: Path, work: Path, models: Path) -> None:
    _link(maps / "Moonlight Maps", work / "import" / "Moonlight Maps")
    for pack in sorted(p for p in (maps / TABLETOP).iterdir() if p.is_dir()):
        if pack.name in HELD:
            # Copied: the browser's folder upload is given this tree
            dest = work / "held" / TABLETOP / pack.name
            if not dest.exists():
                shutil.copytree(pack, dest)
        else:
            _link(pack, work / "import" / TABLETOP / pack.name)

    linked = work / "linked" / "My Maps" / "Fantasy Atlas"
    for src in sorted((maps / "Fantasy Atlas").glob("*/*.jpg")):
        dest = linked / src.parent.name / src.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Skips .tmp, where downloads are staged
    for model in sorted(p for p in models.iterdir() if p.is_dir() and not p.name.startswith(".")):
        _link(model, work / "data" / "models" / model.name)
    print(f"Laid out {work}")


def setup(server: str) -> None:
    with httpx.Client(base_url=f"{server}/api/v1", timeout=60) as client:
        client.put("/tags/packs", json={"packs": ["common", "fantasy"]}).raise_for_status()
        client.post("/models/setup-complete").raise_for_status()
    print("Setup complete")


def main() -> None:
    command, *args = sys.argv[1:]
    if command == "layout":
        models = Path(args[2]) if len(args) > 2 else ROOT / "data" / "models"
        layout(Path(args[0]), Path(args[1]), models)
    elif command == "setup":
        setup(args[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
