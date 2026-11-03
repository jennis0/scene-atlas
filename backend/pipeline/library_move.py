"""Move the library's folders (design/export-backup-move.md §10). Desktop app only: a
server's folders are mounts, and its docs say how to move them.

1. **Copy while the app runs** (``copy_job``): everything in the folder(s) being moved
   but the live database and vector table, each file through ``<name>.part`` and synced;
   imported originals checked against their ``stored_hash`` as they're read. A target
   holds ``scene-atlas-move.json`` while it is being filled.
2. **Restart:** Electron saves the new folders, and starts the backend with the old ones
   as ``--move-from-…`` arguments.
3. **Finish** (``finish_move``, in the sidecar's entry point before the app is imported):
   copy what changed since step 1 (files added, changed or deleted), then the database and
   vector table, and check every imported image's file is in the new store. A failure
   raises ``MoveError``: the sidecar exits with its own code and Electron goes back to the
   old folders, which are untouched.
4. The old folders are kept, their library marker renamed so they no longer open as the
   library, with a note saying where it went; Settings offers to delete them
   (``delete_old``).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

JOB_NAME = "Moving library"
MOVING_FILE = "scene-atlas-move.json"  # in a target being filled
MOVED_NOTE = "scene-atlas-moved.txt"  # in an old folder, saying where it went
MOVED_FROM_KEY = "moved_from"  # app setting: the old folders, for Settings to delete
DB_NAME = "battlemap.db"
_DB_FILES = (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm")
_CHUNK = 1024 * 1024

ProgressFn = Callable[[int, int, str | None], None]


class MoveError(RuntimeError):
    """The move can't be done or finished (shown to the user)."""


def _lock_name() -> str:
    from backend.app.storage_lock import LOCK_FILENAME

    return LOCK_FILENAME


def _marker_name() -> str:
    from backend.app.library_identity import MARKER_FILENAME

    return MARKER_FILENAME


def _skip_live(rel: Path) -> bool:
    """Files the copy while running leaves to the finish: the live database and vectors,
    and this process' lock."""
    top = rel.parts[0]
    return top in _DB_FILES or top == "lancedb" or top == _lock_name() or top == MOVING_FILE


def _files(root: Path, skip: Callable[[Path], bool]) -> Iterator[tuple[Path, Path]]:
    """(absolute, relative) of every file under *root*, but those *skip* names."""
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = Path(dirpath) / name
            rel = path.relative_to(root)
            if not skip(rel) and not name.endswith(".part"):
                yield path, rel


def _copy(src: Path, dst: Path, expected: str | None = None) -> None:
    from backend.pipeline.export_library import copy_verified

    copy_verified(src, dst, expected)


def _same(src: Path, dst: Path) -> bool:
    try:
        a, b = src.stat(), dst.stat()
    except OSError:
        return False
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


# 1. Checks and the copy while the app runs


@dataclass(frozen=True)
class Move:
    """One folder's move."""

    kind: str  # "app_data" | "store"
    source: Path
    target: Path


def _our_copy(target: Path, source: Path) -> bool:
    """*target* is an unfinished copy of *source* (a move tried before): carried on."""
    try:
        record = json.loads((target / MOVING_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(record, dict) and record.get("from") == str(source)


def plan(app_data: str | None, store: str | None) -> list[Move]:
    """The moves asked for, checked: targets absolute, empty (or missing), outside every
    library folder, and on a disk with room. Raises ``MoveError``."""
    from backend.app.config import settings
    from backend.app.library_identity import inside_any

    moves = [
        Move(kind, source, Path(raw))
        for kind, source, raw in (
            ("app_data", settings.data_dir, app_data),
            ("store", settings.store_images_dir, store),
        )
        if raw
    ]
    if not moves:
        raise MoveError("Choose where to move a folder to")
    folders = [settings.data_dir, settings.store_images_dir, settings.linked_library_dir]
    kinds = {m.kind for m in moves}
    if (
        "app_data" in kinds
        and "store" not in kinds
        and inside_any(settings.store_images_dir, [settings.data_dir])
    ):
        raise MoveError("Imported images are inside Search data: move both together")
    targets = [m.target for m in moves]
    if len(targets) == 2 and (
        inside_any(targets[0], [targets[1]]) or inside_any(targets[1], [targets[0]])
    ):
        raise MoveError("Move the two folders to separate places")
    for move in moves:
        target = move.target
        if not target.is_absolute():
            raise MoveError(f"Not an absolute path: {target}")
        if inside_any(target, folders) or inside_any(move.source, [target]):
            raise MoveError(f"{target} is inside the library's folders")
        if target.exists() and any(target.iterdir()) and not _our_copy(target, move.source):
            raise MoveError(f"{target} isn't empty: choose an empty folder")
        parent = target if target.exists() else target.parent
        if not parent.is_dir():
            raise MoveError(f"Folder not found: {parent}")
        needed = sum(p.stat().st_size for p, _ in _files(move.source, lambda _r: False))
        free = shutil.disk_usage(parent).free
        if free < needed + 1024**3:
            raise MoveError(
                f"Not enough space for {move.source.name}: {needed / 1024**3:.1f} GB to "
                f"copy, {free / 1024**3:.1f} GB free"
            )
    return moves


def _stored_hashes() -> dict[str, str]:
    """Storage key → hash, to check each original as it's copied."""
    from sqlalchemy import select

    from backend.app.models.database import Image
    from backend.pipeline.db import pipeline_db

    with pipeline_db() as db:
        return {
            k: h for k, h in db.execute(select(Image.storage_key, Image.stored_hash)) if k and h
        }


def copy_job(moves: list[Move], progress_fn: ProgressFn | None = None) -> dict:
    """Copy the folders while the app runs (step 1). Resumable: files already there with
    the same size and time are skipped. Returns the folders, for Electron's restart."""
    from backend.app.services.shutdown import raise_if_shutting_down

    hashes = _stored_hashes()
    work = [(m, list(_files(m.source, _skip_live))) for m in moves]
    total = sum(len(files) for _, files in work)
    done = 0
    problems: list[str] = []
    for move, files in work:
        move.target.mkdir(parents=True, exist_ok=True)
        (move.target / MOVING_FILE).write_text(
            json.dumps({"from": str(move.source), "kind": move.kind}), "utf-8"
        )
        for src, rel in files:
            raise_if_shutting_down()
            dst = move.target / rel
            if not _same(src, dst):
                try:
                    _copy(src, dst, hashes.get(src.name) if move.kind == "store" else None)
                except FileNotFoundError:
                    pass  # deleted meanwhile: the finish copies what's there then
                except ValueError as e:
                    problems.append(f"{rel}: {e}")
            done += 1
            if progress_fn and done % 200 == 0:
                progress_fn(done, total, f"Copied {done:,} of {total:,} files")
    if problems:
        # A file that doesn't read back as the library recorded it: stop before switching
        raise MoveError(
            f"{len(problems)} file(s) didn't copy correctly, e.g. {problems[0]}. "
            "Nothing has moved; try again, or check the disks."
        )
    return {m.kind: str(m.target) for m in moves}


# 3. Finish, at the next start (before the app opens anything)


def _sync(source: Path, target: Path) -> None:
    """Make *target* hold what *source* does (but the live files, done next)."""
    keep: set[Path] = set()
    for src, rel in _files(source, _skip_live):
        keep.add(rel)
        dst = target / rel
        if not _same(src, dst):
            _copy(src, dst)
    for dst, rel in list(_files(target, _skip_live)):
        if rel not in keep and rel.name != _marker_name():
            dst.unlink()  # deleted since the copy


def _verify(db_path: Path, store: Path) -> None:
    from backend.app.services.image_store import ImageStore

    images = ImageStore(store)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        missing = [
            key
            for (key,) in conn.execute(
                "SELECT storage_key FROM images WHERE storage_key IS NOT NULL"
            )
            if not images.get_path(key).is_file()
        ]
    finally:
        conn.close()
    if missing:
        raise MoveError(
            f"{len(missing)} imported image(s) aren't in the new folder, e.g. {missing[0]}"
        )


def _retire(old: Path, new: Path) -> None:
    """Leave a note in the old folder, and rename its marker so it no longer opens as the
    library (it would be a second copy, drifting apart)."""
    marker = old / _marker_name()
    if marker.exists():
        os.replace(marker, marker.with_name(marker.name + ".moved"))
    (old / MOVED_NOTE).write_text(
        f"This Scene Atlas folder was moved to {new} on {datetime.now(UTC):%Y-%m-%d}.\n"
        "Delete it from Settings → Storage locations, or by hand once you're sure.\n",
        "utf-8",
    )


def finish_move(
    *, app_data: tuple[Path, Path] | None = None, store: tuple[Path, Path] | None = None
) -> None:
    """Finish a move: each of *app_data* and *store* is (old, new). The old folders are
    only read until everything is in place and checked."""
    if app_data is None and store is None:
        return
    logger.info("Finishing the library move: app data %s, images %s", app_data, store)
    if store:
        _sync(*store)
    new_data = app_data[1] if app_data else None
    if app_data:
        old, new = app_data
        _sync(old, new)
        for name in _DB_FILES:
            src, dst = old / name, new / name
            if src.exists():
                _copy(src, dst)
            else:
                dst.unlink(missing_ok=True)
        shutil.rmtree(new / "lancedb", ignore_errors=True)
        if (old / "lancedb").is_dir():
            shutil.copytree(old / "lancedb", new / "lancedb")
    db_dir = new_data or (app_data[0] if app_data else None)
    if db_dir is None:
        from backend.app.config import settings

        db_dir = settings.data_dir
    _verify(db_dir / DB_NAME, store[1] if store else _current_store())
    for old, new in (x for x in (app_data, store) if x):
        (new / MOVING_FILE).unlink(missing_ok=True)
        _retire(old, new)
    _record_moved_from(db_dir / DB_NAME, app_data, store)
    logger.info("Library moved")


def _current_store() -> Path:
    from backend.app.config import settings

    return settings.store_images_dir


def _record_moved_from(db_path: Path, app_data, store) -> None:
    value = {k: str(v[0]) for k, v in (("app_data", app_data), ("store", store)) if v}
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO app_settings (key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (MOVED_FROM_KEY, json.dumps(value)),
        )
        conn.commit()
    finally:
        conn.close()


# 4. The old folders


def moved_from(db) -> dict[str, str] | None:
    """The old folders of the last move still there, for Settings to offer to delete."""
    from backend.app.models.database import AppSetting

    row = db.get(AppSetting, MOVED_FROM_KEY)
    if row is None or not row.value_json:
        return None
    value = json.loads(row.value_json)
    present = {k: v for k, v in value.items() if (Path(v) / MOVED_NOTE).is_file()}
    return present or None


def delete_old(db) -> int:
    """Delete the old folders of the last move: only those with the note the move left,
    and none that is a folder the library uses now. Returns how many went."""
    from backend.app.config import settings
    from backend.app.library_identity import inside_any
    from backend.app.models.database import AppSetting

    gone = 0
    live = [settings.data_dir, settings.store_images_dir, settings.linked_library_dir]
    for path in (moved_from(db) or {}).values():
        folder = Path(path)
        if inside_any(folder, live) or any(inside_any(p, [folder]) for p in live if p):
            continue
        shutil.rmtree(folder)
        gone += 1
    row = db.get(AppSetting, MOVED_FROM_KEY)
    if row is not None:
        db.delete(row)
        db.commit()
    return gone
