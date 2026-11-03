"""Move the library's folders (design/export-backup-move.md §10). Desktop app only: a
server's folders are mounts, and its docs say how to move them.

1. **Copy while the app runs** (``copy_job``): everything in the folder(s) being moved
   but the live database and vector table, each file through ``<name>.part`` and synced;
   imported originals checked against their ``stored_hash`` as they're read. The target
   holds ``scene-atlas-move.json`` (where from, and how far it got) throughout, and the
   app data ``move.json`` (the targets), so Settings offers the restart once it's copied.
2. **Restart:** Electron saves the new folders, and starts the backend with the old ones
   as ``--move-from-…`` arguments until the backend has started on them.
3. **Finish** (``finish_move``, in the sidecar's entry point before the app is imported or
   logs anything): only for a target the copy filled from that very folder. Copy what
   changed since step 1, then the database and vector table, and check every imported
   image's file is in the new store. The old folders are only read. A failure raises
   ``MoveError``: the sidecar exits with its own code and Electron goes back to the old
   folders.
4. **Retire** (``retire_finished``, once the app has opened the new folders): the old
   folders' library markers are renamed so they no longer open as the library, with a
   note saying where it went; Settings offers to delete them (``delete_old``). Until
   then any failed start can go back to them.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import stat
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

JOB_NAME = "Moving library"
MOVING_FILE = "scene-atlas-move.json"  # in a target: {"from", "kind", "state"}
STATE_FILE = "move.json"  # in the app data: the targets of the move being copied
RETIRE_FILE = "move-retire.json"  # in the new app data: the old folders, to retire
MOVED_NOTE = "scene-atlas-moved.txt"  # in an old folder, saying where it went
MOVED_FROM_KEY = "moved_from"  # app setting: the old folders, for Settings to delete
DB_NAME = "battlemap.db"
_DB_FILES = (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm")
# Copied, finished: the target's states. Retired, it has no MOVING_FILE.
COPIED, FINISHED = "copied", "finished"
# File systems round times (exFAT to 10 ms, FAT32 to 2 s): a copy keeps its source's
# time, so a time this close and the same size is the same file
_MTIME_SLACK_NS = 2_000_000_000
_FREE_MARGIN = 1024**3

ProgressFn = Callable[[int, int, str | None], None]


class MoveError(RuntimeError):
    """The move can't be done or finished (shown to the user)."""


def _marker_name() -> str:
    from backend.app.library_identity import MARKER_FILENAME

    return MARKER_FILENAME


def _never_copied(rel: Path) -> bool:
    """Files no copy takes: the live database and vectors (the finish copies those), the
    lock, the move's own records, and an earlier move's retirement."""
    from backend.app.storage_lock import LOCK_FILENAME

    top = rel.parts[0]
    return (
        top in _DB_FILES
        or top in ("lancedb", LOCK_FILENAME, MOVING_FILE, STATE_FILE, RETIRE_FILE, MOVED_NOTE)
        or top == _marker_name() + ".moved"
    )


def _key(rel: Path) -> str:
    """A relative path as compared: HFS+ hands back NFD names for NFC ones."""
    return unicodedata.normalize("NFC", rel.as_posix())


def _files(root: Path, skip: Callable[[Path], bool] = _never_copied) -> Iterator[tuple[Path, Path]]:
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
    return a.st_size == b.st_size and abs(a.st_mtime_ns - b.st_mtime_ns) <= _MTIME_SLACK_NS


def _record(target: Path) -> dict | None:
    try:
        value = json.loads((target / MOVING_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_record(target: Path, source: Path, kind: str, state: str | None) -> None:
    record = {"from": str(source), "kind": kind, "state": state}
    (target / MOVING_FILE).write_text(json.dumps(record), "utf-8")


# 1. Checks and the copy while the app runs


@dataclass(frozen=True)
class Move:
    """One folder's move."""

    kind: str  # "app_data" | "store"
    source: Path
    target: Path


def movable() -> dict[str, bool]:
    """Which folders Settings can offer to move: not Search data alone when Imported
    images is inside it (an old layout)."""
    from backend.app.config import settings
    from backend.app.library_identity import inside_any

    return {
        "app_data": not inside_any(settings.store_images_dir, [settings.data_dir]),
        "store": True,
    }


def plan(app_data: str | None, store: str | None) -> list[Move]:
    """The moves asked for, checked: targets absolute, empty (or this move's unfinished
    copy), apart, and outside every library folder. Raises ``MoveError``."""
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
    if any(m.kind == "app_data" for m in moves) and not movable()["app_data"]:
        raise MoveError("Imported images are inside Search data, so they can't move apart")
    folders = [settings.data_dir, settings.store_images_dir, settings.linked_library_dir]
    if len(moves) == 2 and (
        inside_any(moves[0].target, [moves[1].target])
        or inside_any(moves[1].target, [moves[0].target])
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
    return moves


def _our_copy(target: Path, source: Path) -> bool:
    """*target* holds a copy this move made of *source* (finished or not)."""
    record = _record(target)
    return record is not None and record.get("from") == str(source)


def _state_path() -> Path:
    from backend.app.config import settings

    return settings.data_dir / STATE_FILE


def copy_status() -> dict[str, str] | None:
    """The targets of a copy that has finished and waits for the restart, else None."""
    try:
        targets = json.loads(_state_path().read_text("utf-8"))
    except (OSError, ValueError):
        return None
    ready = all((_record(Path(t)) or {}).get("state") == COPIED for t in targets.values())
    return targets if targets and ready else None


def cancel() -> None:
    """Forget a copied move that wasn't applied, deleting its copies."""
    from backend.app.config import settings

    try:
        targets = json.loads(_state_path().read_text("utf-8"))
    except (OSError, ValueError):
        targets = {}
    sources = {"app_data": settings.data_dir, "store": settings.store_images_dir}
    for kind, target in targets.items():
        if _our_copy(Path(target), sources[kind]):
            shutil.rmtree(target, ignore_errors=True)
    _state_path().unlink(missing_ok=True)


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
    the same size and time are skipped. Returns the new folders, for the restart."""
    from backend.app.services.shutdown import raise_if_shutting_down

    hashes = _stored_hashes()
    work = [(m, list(_files(m.source))) for m in moves]
    for move, files in work:
        move.target.mkdir(parents=True, exist_ok=True)
        needed = sum(src.stat().st_size for src, rel in files if not _same(src, move.target / rel))
        free = shutil.disk_usage(move.target).free
        if free < needed + _FREE_MARGIN:
            raise MoveError(
                f"Not enough space in {move.target}: {needed / 1024**3:.1f} GB to copy, "
                f"{free / 1024**3:.1f} GB free"
            )
    _state_path().write_text(json.dumps({m.kind: str(m.target) for m in moves}), "utf-8")
    total = sum(len(files) for _, files in work)
    done = 0
    problems: list[str] = []
    for move, files in work:
        _write_record(move.target, move.source, move.kind, None)
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
            f"{len(problems)} file(s) didn't copy correctly, e.g. {problems[0]}. Nothing has "
            "moved; try again (an original changed since it was imported fails until it's "
            "imported again), or check the disks."
        )
    for move in moves:
        _write_record(move.target, move.source, move.kind, COPIED)
    return {m.kind: str(m.target) for m in moves}


# 3. Finish, at the next start (before the app opens anything)


def _sync(source: Path, target: Path) -> None:
    """Make *target* hold what *source* does (the live files aside: done next). Only
    files a copy would take are deleted from the target."""
    keep: set[str] = set()
    for src, rel in _files(source):
        keep.add(_key(rel))
        dst = target / rel
        if not _same(src, dst):
            _copy(src, dst)
    for dst, rel in list(_files(target)):
        if _key(rel) not in keep:
            dst.unlink()  # deleted since the copy


def _copy_tree(source: Path, target: Path) -> None:
    """A folder copied file by file, each synced (the vector table)."""
    shutil.rmtree(target, ignore_errors=True)
    for src, rel in _files(source, skip=lambda _r: False):
        _copy(src, target / rel)


def _verify(db_path: Path, store: Path, old_store: Path | None) -> None:
    """Every imported image whose file was in the old store is in *store*. (Ones missing
    from the old store already are logged, not held against the move: they were lost
    before it, and would stop it for ever.)"""
    from backend.app.services.image_store import ImageStore

    images = ImageStore(store)
    old = ImageStore(old_store) if old_store else None
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)  # C:\ too
    try:
        missing, lost_before = [], 0
        for (key,) in conn.execute("SELECT storage_key FROM images WHERE storage_key IS NOT NULL"):
            if images.get_path(key).is_file():
                continue
            if old is not None and not old.get_path(key).is_file():
                lost_before += 1
            else:
                missing.append(key)
    finally:
        conn.close()
    if lost_before:
        logger.warning("%d imported image(s) were already missing before the move", lost_before)
    if missing:
        raise MoveError(
            f"{len(missing)} imported image(s) aren't in the new folder, e.g. {missing[0]}"
        )


def _to_do(pair: tuple[Path, Path] | None) -> bool:
    """Whether *pair* (old, new) still needs finishing. Refuses (``MoveError``) one that
    isn't this move's copy: the finish deletes files in the new folder."""
    if pair is None:
        return False
    old, new = pair
    if old.exists() and new.exists() and os.path.samefile(old, new):
        raise MoveError(f"{new} is the folder it would be moved from")
    record = _record(new)
    if record is not None and record.get("from") == str(old):
        if record.get("state") == FINISHED:
            return False  # finished, not yet retired: the app retires it
        if record.get("state") == COPIED:
            return True
        raise MoveError(f"The copy to {new} didn't finish; move it again from Settings")
    if (old / MOVED_NOTE).is_file() and (new / _marker_name()).is_file():
        return False  # moved and retired already: a start after the move
    raise MoveError(f"{new} isn't a copy of {old}")


def finish_move(
    *, app_data: tuple[Path, Path] | None = None, store: tuple[Path, Path] | None = None
) -> None:
    """Finish a move: each of *app_data* and *store* is (old, new). The old folders are
    only read. Holds both folders' locks, so a backend that hasn't quite stopped can't
    write to them meanwhile."""
    from backend.app.config import settings
    from backend.app.storage_lock import acquire_storage_lock

    pairs = {"app_data": app_data, "store": store}
    to_do = {kind: pair for kind, pair in pairs.items() if _to_do(pair)}
    if not to_do:
        return
    logger.info("Finishing the library move: %s", to_do)
    locks = [
        acquire_storage_lock(root, timeout=15)
        for pair in to_do.values()
        for root in pair  # type: ignore[union-attr]
    ]
    try:
        if "store" in to_do:
            _sync(*to_do["store"])  # type: ignore[misc]
        if "app_data" in to_do:
            old, new = to_do["app_data"]  # type: ignore[misc]
            _sync(old, new)
            for name in _DB_FILES:
                if (old / name).exists():
                    _copy(old / name, new / name)
                else:
                    (new / name).unlink(missing_ok=True)
            if (old / "lancedb").is_dir():
                _copy_tree(old / "lancedb", new / "lancedb")
        data_dir = to_do["app_data"][1] if "app_data" in to_do else settings.data_dir  # type: ignore[index]
        new_store = to_do["store"][1] if "store" in to_do else settings.store_images_dir  # type: ignore[index]
        old_store = to_do["store"][0] if "store" in to_do else new_store  # type: ignore[index]
        _verify(data_dir / DB_NAME, new_store, old_store)
        retire = {kind: [str(p) for p in pair] for kind, pair in to_do.items()}  # type: ignore[union-attr]
        (data_dir / RETIRE_FILE).write_text(json.dumps(retire), "utf-8")
        for kind, (old, new) in to_do.items():  # type: ignore[misc]
            _write_record(new, old, kind, FINISHED)
    finally:
        for lock in locks:
            lock.release()
    logger.info("Library move finished; the old folders are retired once the app opens")


# 4. Retire, once the app has opened the new folders


def retire_finished(db) -> None:
    """After a move's first successful start: retire the old folders (the marker renamed,
    a note left) and record them for Settings."""
    from backend.app.config import settings
    from backend.app.models.database import AppSetting

    path = settings.data_dir / RETIRE_FILE
    try:
        retire = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return
    live = {"app_data": settings.data_dir, "store": settings.store_images_dir}
    if not all(_same_folder(Path(new), live[kind]) for kind, (_old, new) in retire.items()):
        # Started on the old folders after all (a failed start went back to them): the move
        # isn't done. Its copies wait to be restarted onto, or cancelled, again.
        for kind, (old, new) in retire.items():
            if _our_copy(Path(new), Path(old)):
                _write_record(Path(new), Path(old), kind, COPIED)
        path.unlink(missing_ok=True)
        logger.warning("Library move not applied: the app started on the old folders")
        return
    moved_from: dict[str, str] = {}
    for kind, (old, new) in retire.items():
        old_path, new_path = Path(old), Path(new)
        marker = old_path / _marker_name()
        if marker.exists():
            os.replace(marker, marker.with_name(marker.name + ".moved"))
        (old_path / MOVED_NOTE).write_text(
            f"This Scene Atlas folder was moved to {new_path} on {datetime.now(UTC):%Y-%m-%d}.\n"
            "Delete it from Settings → Storage locations, or by hand once you're sure.\n",
            "utf-8",
        )
        (new_path / MOVING_FILE).unlink(missing_ok=True)
        moved_from[kind] = old
    row = db.get(AppSetting, MOVED_FROM_KEY)
    if row is None:
        db.add(AppSetting(key=MOVED_FROM_KEY, value_json=json.dumps(moved_from)))
    else:
        row.value_json = json.dumps(moved_from)
    db.commit()
    path.unlink(missing_ok=True)
    (settings.data_dir / STATE_FILE).unlink(missing_ok=True)
    logger.info("Library moved; the old folders are kept until deleted: %s", moved_from)


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def unretire_live(db) -> None:
    """A folder in use with a moved note was gone back to (a move's start failed after it
    was retired): it's the library again, so the note and the record go."""
    from backend.app.config import settings
    from backend.app.models.database import AppSetting

    for folder in (settings.data_dir, settings.store_images_dir):
        note = folder / MOVED_NOTE
        if not note.is_file():
            continue
        note.unlink()
        marker = folder / (_marker_name() + ".moved")
        if marker.exists() and not (folder / _marker_name()).exists():
            os.replace(marker, folder / _marker_name())
        row = db.get(AppSetting, MOVED_FROM_KEY)
        if row is not None and str(folder) in json.loads(row.value_json or "{}").values():
            db.delete(row)
            db.commit()
        logger.warning("%s was a moved library's old folder, and is in use again", folder)


# The old folders


def moved_from(db) -> dict[str, str] | None:
    """The old folders of the last move still there, for Settings to offer to delete."""
    from backend.app.models.database import AppSetting

    row = db.get(AppSetting, MOVED_FROM_KEY)
    if row is None or not row.value_json:
        return None
    value = json.loads(row.value_json)
    present = {k: v for k, v in value.items() if (Path(v) / MOVED_NOTE).is_file()}
    return present or None


def _writable_then_retry(func, path, _exc) -> None:
    """``rmtree``'s handler: Windows refuses to delete read-only files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def delete_old(db) -> dict:
    """Delete the old folders of the last move: only those with the note the move left,
    and none inside, or holding, a folder the library uses now (those are kept, and
    said). The record goes once nothing is left of it."""
    from backend.app.config import settings
    from backend.app.library_identity import inside_any
    from backend.app.models.database import AppSetting

    deleted, kept = 0, []
    live: list[Path | None] = [
        p for p in (settings.data_dir, settings.store_images_dir, settings.linked_library_dir) if p
    ]
    for path in (moved_from(db) or {}).values():
        folder = Path(path)
        if inside_any(folder, live) or any(p and inside_any(p, [folder]) for p in live):
            kept.append(f"{folder} (it's inside, or holds, a folder in use: delete it by hand)")
            continue
        try:
            shutil.rmtree(folder, onerror=_writable_then_retry)
            deleted += 1
        except OSError as e:
            kept.append(f"{folder} ({e.strerror or e})")
    if not kept:
        row = db.get(AppSetting, MOVED_FROM_KEY)
        if row is not None:
            db.delete(row)
            db.commit()
    return {"deleted": deleted, "kept": kept}
