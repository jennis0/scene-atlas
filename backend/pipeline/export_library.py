"""Export the whole library as a folder (design/export-backup-move.md §7).

Every image's original, in the readable layout (``naming.ReadableLayout``), with a
``scene-atlas.jsonl`` (kind ``groups``) that re-imports it with its names, groups, tags,
grids and vectors. Useful outside Scene Atlas too: the folder is plain files.

A background job (or the CLI). Groups are written in id order: each group's files are
copied, each verified against its ``stored_hash`` while it is read, and then the group's
line is appended to ``scene-atlas.jsonl``, so the metadata is never ahead of the files.

**Resume.** Run into the folder of an unfinished export of this library, it carries on.
A torn last line (the process killed while writing it) is cut off, and the last group
listed is placed again, since its lines may not all have been written. The other groups
its ``scene-atlas.jsonl`` lists were written and verified, and are skipped (ungrouped
images by their hash). A group placed again keeps its name unless the library changed,
and its files that are already there with the right hash aren't copied again. Names the
listed groups use are taken, so a group deleted or renamed in between can't send another
into their folders. Files skipped in a group already listed are not retried: export into
a new folder for those.

Not a snapshot: an export of a large library takes hours, and a read transaction that
long would keep SQLite's WAL from being checkpointed. Each group's line is consistent
with its files; a group edited while the export runs is written as it was when reached.

Usage:
    uv run python -m backend.pipeline.export_library <output_dir>
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import logging
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select

from backend.app.config import settings
from backend.app.models.database import Image, ImageGroup, listed_images
from backend.app.services.originals import OriginalUnavailable, original_path
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline import library_format as lf
from backend.pipeline.db import pipeline_db
from backend.pipeline.naming import ReadableLayout, windows_len

logger = logging.getLogger(__name__)

JOB_NAME = "Exporting library"
_CHUNK = 1024 * 1024
# Kept free on the target, beyond the group about to be written; more when it is the
# library's own disk, which the database and imports also need
_FREE_MARGIN = 512 * 1024 * 1024
_SHARED_DISK_MARGIN = 5 * 1024**3
PROBLEMS_FILE = "scene-atlas-export-problems.txt"
# What a file manager leaves in a folder it has shown: the folder is still empty
_JUNK = {".ds_store", "thumbs.db", "desktop.ini", ".localized"}
# A per-file problem (a name the target refuses) skips that file; these stop the export
_FATAL = {errno.ENOSPC, errno.EIO, errno.EROFS, errno.EDQUOT}
_MAX_PROBLEMS_LISTED = 50

ProgressFn = Callable[[int, int, str | None], None]


class ExportStopped(OSError):
    """The export can't go on (a full or failing disk); run it again to resume."""


_PREFIX = "scene-atlas-export-"


def server_exports_dir() -> Path:
    """Where a server writes full exports: in the images folder, which its admin can reach
    on the host."""
    return settings.store_images_dir / "exports"


def server_export_dir(now: datetime | None = None) -> Path:
    """A new export's folder on a server."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return server_exports_dir() / f"{_PREFIX}{stamp}"


def latest_server_export() -> Path | None:
    """The newest export folder on a server (the names sort by time)."""
    root = server_exports_dir()
    if not root.is_dir():
        return None
    found = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(_PREFIX))
    return found[-1] if found else None


@dataclass
class _Resume:
    """What an unfinished export in the folder already holds."""

    groups: set[str] = field(default_factory=set)  # uids of groups written
    ungrouped: set[str] = field(default_factory=set)  # keys of ungrouped images written
    taken: set[str] = field(default_factory=set)  # top-level names they use
    images: int = 0
    started: bool = False  # the header is there


def _ungrouped_key(
    stored_hash: str | None, content_hash: str | None, filename: str, size: int | None
) -> str:
    """How a resumed export recognises an ungrouped image it wrote."""
    return stored_hash or content_hash or f"name:{filename}:{size}"


def _not_ours() -> ExportStopped:
    return ExportStopped(
        errno.EEXIST, "That folder holds something else, not this library's export"
    )


def _read_resume(path: Path, library_id: str | None) -> _Resume:
    """Read an unfinished export's ``scene-atlas.jsonl`` in one streaming pass (it is a
    gigabyte for a large library), keeping only what a resume needs, and cut it back to
    what was surely finished: whole lines, and not the last group's lines (see the module
    docstring)."""
    resume = _Resume()
    if not path.exists() or path.stat().st_size == 0:
        return resume
    good_end = 0  # where the finished part of the file ends
    offset = 0
    run_uid: str | None = None  # the group whose lines are being read
    run: list[list] = []  # its lines' images, counted once a later line shows it complete

    def count(images: list, uid: str | None) -> None:
        for image in images:
            if not isinstance(image, dict):
                continue
            rel = image.get("path")
            if isinstance(rel, str) and rel:
                resume.taken.add(PurePosixPath(rel).parts[0])
            if uid is None:
                resume.ungrouped.add(
                    _ungrouped_key(
                        image.get("stored_hash"),
                        image.get("content_hash"),
                        str(image.get("filename", "")),
                        image.get("file_size"),
                    )
                )
            resume.images += 1
        if uid is not None:
            resume.groups.add(uid)

    with path.open("rb") as fp:
        for raw in fp:
            start, offset = offset, offset + len(raw)
            try:
                obj = json.loads(raw) if raw.endswith(b"\n") else None
            except ValueError:
                obj = None
            if not isinstance(obj, dict):
                if not resume.started and not raw.startswith(b'{"format"'):
                    raise _not_ours()  # not a torn header of ours: someone else's file
                break  # a write the process was killed in
            if not resume.started:
                try:
                    header = lf.Header.model_validate(obj)
                except ValueError:
                    raise _not_ours() from None
                if not (
                    header.kind == lf.KIND_GROUPS
                    and library_id is not None
                    and header.library_id == library_id
                ):
                    raise _not_ours()
                resume.started = True
                good_end = offset
                continue
            group = obj.get("group")
            uid = group.get("uid") if isinstance(group, dict) else None
            found = obj.get("images")
            images: list = found if isinstance(found, list) else []
            if uid is None or uid != run_uid:
                for line in run:  # a different line: the group before it was complete
                    count(line, run_uid)
                run, run_uid = [], None
                good_end = start
            if uid is None:
                count(images, None)  # an ungrouped line is complete in itself
                good_end = offset
            else:
                run_uid = uid
                run.append(images)
    # The last group's lines (in `run`) are dropped: it is placed again
    with path.open("r+b") as fp:
        fp.truncate(good_end)
    return resume


def check_export_header(path: Path, library_id: str | None) -> None:
    """Refuse (``ExportStopped``) a folder whose ``scene-atlas.jsonl`` isn't the start of
    this library's export, reading only its first line."""
    metadata = path / lf.FILENAME
    if not metadata.is_file() or metadata.stat().st_size == 0:
        return
    with metadata.open("rb") as fp:
        first = fp.readline(lf.MAX_LINE_CHARS)
    try:
        header = lf.Header.model_validate(json.loads(first))
    except ValueError:
        if first.endswith(b"\n") or not first.startswith(b'{"format"'):
            raise _not_ours() from None
        return  # a torn header of ours: it starts again
    if header.kind != lf.KIND_GROUPS or library_id is None or header.library_id != library_id:
        raise _not_ours()


def check_target(path: Path) -> None:
    """Refuse a folder that isn't empty (a file manager's own files aside) unless it holds
    an export (whose header ``export_library`` then checks). Raises ``ValueError``."""
    if not path.is_dir():
        raise ValueError(f"Folder not found: {path}")
    if (path / lf.FILENAME).is_file():
        return
    if any(entry.name.lower() not in _JUNK for entry in path.iterdir()):
        # Its files would be mixed with the export's, and a re-import would take them too
        raise ValueError("That folder isn't empty. Choose an empty one, or an unfinished export.")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while chunk := fp.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def copy_verified(source: Path, target: Path, expected: str | None) -> None:
    """Copy *source* to *target* through ``<target>.part``, hashing what is read: a source
    that doesn't match *expected* (its bytes changed, or the disk returned bad ones) is
    refused with ``ValueError``. Synced before the rename, so a crash leaves only a
    ``.part``. Already there with the expected hash: nothing is copied. The source's
    modification time is kept; its permissions aren't (a read-only original would make
    the copy read-only)."""
    if (
        target.exists()
        and expected
        and target.stat().st_size == source.stat().st_size
        and _hash_file(target) == expected
    ):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as src, part.open("wb") as dst:
            while chunk := src.read(_CHUNK):
                digest.update(chunk)
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if expected and digest.hexdigest() != expected:
            raise ValueError("its bytes don't match the library's record of them")
        stat = source.stat()
        with contextlib.suppress(OSError):  # a target that can't set times still gets it
            os.utime(part, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def _same_disk(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False


def _same_size(path: Path, size: int) -> bool:
    try:
        return path.stat().st_size == size
    except OSError:
        return False


def _check_space(dest: Path, needed: int, margin: int) -> None:
    free = shutil.disk_usage(dest).free
    if free < needed + margin:
        raise ExportStopped(
            errno.ENOSPC,
            f"Not enough space: {needed / 1024**3:.1f} GB to write, "
            f"{free / 1024**3:.1f} GB free. Make room and export again to carry on.",
        )


def _clean_parts(dest: Path) -> None:
    """Half-written files from a run that was killed."""
    for part in dest.rglob("*.part"):
        part.unlink(missing_ok=True)


def export_library(
    output_dir: str | Path,
    progress_fn: ProgressFn | None = None,
    *,
    include_linked: bool = True,
) -> dict:
    """Export every listed image into *output_dir* (created if need be), or carry on an
    unfinished export there. Returns ``path``, how many ``images`` the folder holds, how
    many were ``skipped`` (unreadable or refused by the target) and the first
    ``problems``; every problem is also written to ``scene-atlas-export-problems.txt``."""
    from backend.app.library_identity import get_library_id
    from backend.app.services.lancedb_service import get_lancedb_service
    from backend.pipeline.metadata_export import model_info, vector_lookup

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    check_target(dest)
    metadata = dest / lf.FILENAME
    with pipeline_db() as db:
        library_id = get_library_id(db)
    if progress_fn and metadata.exists():
        progress_fn(0, 0, "Reading the unfinished export…")
    resume = _read_resume(metadata, library_id)
    _clean_parts(dest)
    layout = ReadableLayout(root_len=windows_len(str(dest.resolve())), taken=resume.taken)
    margin = (
        _SHARED_DISK_MARGIN
        if _same_disk(dest, settings.data_dir) or _same_disk(dest, settings.images_dir)
        else _FREE_MARGIN
    )
    problems: list[str] = []
    skipped = 0
    written = resume.images
    sources: dict[int, tuple[Path, int]] = {}  # this group's readable originals, and sizes
    failed: set[str] = set()  # paths not written in this group

    def note(problem: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(problems) < _MAX_PROBLEMS_LISTED:
            problems.append(problem)
        logger.warning("Export: %s", problem)
        try:
            with (dest / PROBLEMS_FILE).open("a", encoding="utf-8") as fp:
                fp.write(problem + "\n")
        except OSError:
            pass

    def keep(group: ImageGroup | None, images: list[Image]) -> list[Image]:
        """The images to write: not already in the folder, and readable."""
        if group is not None and group.uid in resume.groups:
            return []
        sources.clear()
        kept = []
        for img in images:
            if group is None and (
                _ungrouped_key(img.stored_hash, img.content_hash, img.filename, img.file_size)
                in resume.ungrouped
            ):
                continue
            try:
                path = original_path(img)
                sources[img.id] = (path, path.stat().st_size)
            except OriginalUnavailable as exc:
                note(f"{img.filename}: {exc.reason}")
                continue
            except OSError as exc:
                note(f"{img.filename}: {exc.strerror or exc}")
                continue
            kept.append(img)
        return kept

    def place(group: ImageGroup | None, images: Sequence[Image]) -> list[str]:
        """Name the group's files, and write them, before its line is."""
        flush()  # the previous group is done: its line goes down before more is written
        raise_if_shutting_down()
        paths = layout.place_images(group, images, order)
        needed = sum(
            sources[img.id][1]
            for img, path in zip(images, paths, strict=True)
            if not _same_size(dest / path, sources[img.id][1])  # there: a resume skips it
        )
        _check_space(dest, needed, margin)
        failed.clear()
        for img, path in zip(images, paths, strict=True):
            raise_if_shutting_down()
            try:
                copy_verified(sources[img.id][0], dest / path, img.stored_hash)
            except OSError as exc:
                if exc.errno in _FATAL:
                    raise ExportStopped(exc.errno, f"Writing {path} failed: {exc}") from exc
                failed.add(path)
                note(f"{path}: {exc.strerror or exc}")
            except ValueError as exc:
                failed.add(path)
                note(f"{img.filename}: {exc}")
        return paths

    with pipeline_db() as db:
        condition = None if include_linked else Image.storage_key.isnot(None)
        filters = [listed_images(), *([condition] if condition is not None else [])]
        total, max_id, size = db.execute(
            select(func.count(Image.id), func.max(Image.id), func.sum(Image.file_size)).where(
                *filters
            )
        ).one()
        if not resume.started:
            # A first look, so an export that can't fit doesn't start; checked per group too
            _check_space(dest, int(size or 0), margin)
        order = lf.tag_category_order(db)
        svc = get_lancedb_service()
        scratch = settings.metadata_exports_dir / f"{uuid.uuid4().hex}.vectors"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        with (
            vector_lookup(svc, max_id or 0, scratch) as vectors,
            metadata.open("a", encoding="utf-8") as out,
        ):

            def write(text: str) -> None:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())

            if not resume.started:
                header = lf.header_line(
                    db,
                    kind=lf.KIND_GROUPS,
                    app_version=settings.app_version,
                    library_id=library_id,  # so only this library's export is carried on
                    model=model_info(svc),
                )
                write(lf.dump_line(header))  # on disk at once: a resume needs it
            pending: list[str] = []  # the current group's lines, written together
            pending_uid: str | None = None

            def flush() -> None:
                if pending:
                    write("".join(pending))
                    pending.clear()

            for line in lf.group_lines(
                db,
                kind=lf.KIND_GROUPS,
                vectors=vectors,
                condition=condition,
                place=place,
                keep=keep,
            ):
                uid = line.group.uid if line.group else None
                if uid is None or uid != pending_uid:
                    flush()
                pending_uid = uid
                primary = None
                if line.group and line.group.primary is not None:
                    primary = line.images[line.group.primary].path
                line.images = [img for img in line.images if img.path not in failed]
                if not line.images:
                    continue
                if line.group:
                    paths = [img.path for img in line.images]
                    line.group.primary = paths.index(primary) if primary in paths else None
                pending.append(lf.dump_line(line))
                written += len(line.images)
                if progress_fn:
                    progress_fn(written, total, f"Exported {written:,} of {total:,} images")
            flush()

    logger.info("Library export: %d images, %d skipped -> %s", written, skipped, dest)
    return {"path": str(dest), "images": written, "skipped": skipped, "problems": problems}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        print("Usage: python -m backend.pipeline.export_library <output_dir>")
        sys.exit(2)
    out = Path(sys.argv[1])
    print(f"Exporting library to: {out}")
    try:
        result = export_library(out)
    except (ValueError, OSError) as e:  # FormatError is a ValueError; ExportStopped an OSError
        print(e)
        sys.exit(1)
    print(f"Done: {result['images']} image(s) in the folder, {result['skipped']} skipped.")
