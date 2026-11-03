"""Export the whole library as a folder (design/export-backup-move.md §7).

Every image's original, in the readable layout (``naming.ReadableLayout``), with a
``scene-atlas.jsonl`` (kind ``groups``) that re-imports it with its names, groups, tags,
grids and vectors. Useful outside Scene Atlas too: the folder is plain files.

A background job (or the CLI). Groups are written in id order: each group's files are
copied, each verified against its ``stored_hash`` while it is read, and then the group's
line is appended to ``scene-atlas.jsonl``, so the metadata is never ahead of the files.

**Resume.** Run into the folder of an unfinished export, it carries on. The groups its
``scene-atlas.jsonl`` lists were written and verified, and are skipped (ungrouped images
by their hash). The group being written when it stopped has no line yet: it is placed
again, under the same name unless the library changed, and its files that are already
there with the right size and hash aren't copied again. Names the listed groups use are
taken, so a group deleted or renamed in between can't send another into their folders.

Not a snapshot: an export of a large library takes hours, and a read transaction that
long would keep SQLite's WAL from being checkpointed. Each group's line is consistent
with its files; a group edited while the export runs is written as it was when reached.

Usage:
    uv run python -m backend.pipeline.export_library <output_dir>
"""

from __future__ import annotations

import errno
import hashlib
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
from backend.pipeline.naming import ReadableLayout

logger = logging.getLogger(__name__)

JOB_NAME = "Exporting library"
_CHUNK = 1024 * 1024
# Kept free on the target, beyond the group about to be written
_FREE_MARGIN = 512 * 1024 * 1024
# A per-file problem (a name the target refuses) skips that file; these stop the export
_FATAL = {errno.ENOSPC, errno.EIO, errno.EROFS, errno.EDQUOT}
_MAX_PROBLEMS_LISTED = 50

ProgressFn = Callable[[int, int, str | None], None]


class ExportStopped(OSError):
    """The export can't go on (a full or failing disk); run it again to resume."""


def server_export_dir(now: datetime | None = None) -> Path:
    """Where a server writes a full export: in the images folder, which its admin can
    reach on the host."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return settings.images_dir / "exports" / f"scene-atlas-export-{stamp}"


@dataclass
class _Resume:
    """What an unfinished export in the folder already holds."""

    groups: set[str] = field(default_factory=set)  # uids of groups written
    ungrouped: set[str] = field(default_factory=set)  # hashes of ungrouped images written
    taken: set[str] = field(default_factory=set)  # top-level names they use
    images: int = 0
    started: bool = False  # the header is there


def _read_resume(path: Path) -> _Resume:
    resume = _Resume()
    if not path.exists():
        return resume
    with lf.open_file(path) as fp:
        for line in lf.read_lines(fp):
            if isinstance(line, lf.Header):
                resume.started = True
            elif isinstance(line, lf.GroupLine):
                for image in line.images:
                    if image.path:
                        resume.taken.add(PurePosixPath(image.path).parts[0])
                    if line.group is None and image.stored_hash:
                        resume.ungrouped.add(image.stored_hash)
                    resume.images += 1
                if line.group is not None:
                    resume.groups.add(line.group.uid)
    return resume


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
    ``.part``. Already there with the expected hash: nothing is copied."""
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
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    shutil.copystat(source, target, follow_symlinks=False)


def _check_space(dest: Path, needed: int) -> None:
    free = shutil.disk_usage(dest).free
    if free < needed + _FREE_MARGIN:
        raise ExportStopped(
            errno.ENOSPC,
            f"Not enough space: {needed / 1024**3:.1f} GB to write, "
            f"{free / 1024**3:.1f} GB free. Make room and export again to carry on.",
        )


def export_library(
    output_dir: str | Path,
    progress_fn: ProgressFn | None = None,
    *,
    include_linked: bool = True,
) -> dict:
    """Export every listed image into *output_dir* (created if need be), or carry on an
    unfinished export there. Returns ``path``, how many ``images`` the folder holds, how
    many were ``skipped`` (unreadable or refused by the target) and the first
    ``problems``."""
    from backend.app.services.lancedb_service import get_lancedb_service
    from backend.pipeline.metadata_export import model_info, vector_lookup

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    metadata = dest / lf.FILENAME
    resume = _read_resume(metadata)
    layout = ReadableLayout(root_len=len(str(dest.resolve())), taken=resume.taken)
    problems: list[str] = []
    skipped = 0
    written = resume.images
    sources: dict[int, Path] = {}  # this group's readable originals
    failed: set[str] = set()  # paths not written in this group

    def note(problem: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(problems) < _MAX_PROBLEMS_LISTED:
            problems.append(problem)
        logger.warning("Export: %s", problem)

    def keep(group: ImageGroup | None, images: list[Image]) -> list[Image]:
        """The images to write: not already in the folder, and readable."""
        if group is not None and group.uid in resume.groups:
            return []
        sources.clear()
        kept = []
        for img in images:
            if group is None and img.stored_hash in resume.ungrouped:
                continue
            try:
                sources[img.id] = original_path(img)
            except OriginalUnavailable as exc:
                note(f"{img.filename}: {exc.reason}")
                continue
            kept.append(img)
        return kept

    def place(group: ImageGroup | None, images: Sequence[Image]) -> list[str]:
        """Name the group's files, and write them, before its line is."""
        flush()  # the previous group is done: its line goes down before more is written
        raise_if_shutting_down()
        paths = layout.place_images(group, images, order)
        _check_space(dest, sum(sources[img.id].stat().st_size for img in images))
        failed.clear()
        for img, path in zip(images, paths, strict=True):
            raise_if_shutting_down()
            try:
                copy_verified(sources[img.id], dest / path, img.stored_hash)
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
        total, max_id = db.execute(
            select(func.count(Image.id), func.max(Image.id)).where(
                listed_images(), *([condition] if condition is not None else [])
            )
        ).one()
        order = lf.tag_category_order(db)
        svc = get_lancedb_service()
        scratch = settings.metadata_exports_dir / f"{uuid.uuid4().hex}.vectors"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        with (
            vector_lookup(svc, max_id or 0, scratch) as vectors,
            metadata.open("a", encoding="utf-8") as out,
        ):
            if not resume.started:
                header = lf.header_line(
                    db,
                    kind=lf.KIND_GROUPS,
                    app_version=settings.app_version,
                    library_id=None,
                    model=model_info(svc),
                )
                out.write(lf.dump_line(header))
            pending: list[str] = []  # the current group's lines, written together
            pending_uid: str | None = None

            def flush() -> None:
                if pending:
                    out.write("".join(pending))
                    out.flush()
                    os.fsync(out.fileno())
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
                line.images = [img for img in line.images if img.path not in failed]
                if not line.images:
                    continue
                if (
                    line.group
                    and line.group.primary is not None
                    and line.group.primary >= len(line.images)
                ):
                    line.group.primary = None
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
    out = sys.argv[1]
    print(f"Exporting library to: {out}")
    result = export_library(out)
    print(f"Done: {result['images']} image(s) in the folder, {result['skipped']} skipped.")
