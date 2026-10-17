"""Local imports: items read from files and folders on this computer (design/local-ingest.md).

In the desktop app the user picks or drops folders and files; the client sends their
paths (the roots) and the server lists them, instead of the browser walking the tree and
uploading every file. Each file becomes an item with ``source_path`` set and its bytes
already available (``ready``); the worker reads it from there and copies it into the
library. Sources are never written, moved or deleted.

Relative paths are taken from each root's parent, so a folder's paths start with its
name: the same shape as a browser folder pick, so parsing and grouping are unchanged.
Directory symlinks are not followed (no cycles, no leaving the chosen tree), and nor are
file symlinks.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from backend.app.models import ImportItem, ImportJob
from backend.app.services import ingest_state as st

from .ingest_archive import ArchiveCounts, expand_archive
from .ingest_queue import (
    ManifestEntry,
    ManifestSealedError,
    add_manifest_items,
    is_os_junk,
    kind_for_path,
    normalise_relative_path,
)


class LocalSourceError(ValueError):
    """A root the client named can't be read (not absolute, missing, not a file or folder)."""


class TooManyLocalFilesError(Exception):
    """The roots hold more files than one import may contain."""

    def __init__(self, limit: int):
        super().__init__(f"An import can contain at most {limit:,} files")
        self.limit = limit


@dataclass(frozen=True)
class LocalFile:
    relative_path: str
    source_path: Path
    size: int
    last_modified: int  # ms since epoch, as the browser reports it


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int
    max_uncompressed_bytes: int


@dataclass
class LocalCounts:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    ignored: int = 0  # OS junk and paths already in the import


def resolve_roots(paths: Iterable[str]) -> list[Path]:
    """Absolute, existing files or folders, normalised, duplicates dropped."""
    roots: dict[Path, None] = {}
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            raise LocalSourceError(f"Not an absolute path: {raw}")
        try:
            path = path.resolve(strict=True)
        except OSError:
            raise LocalSourceError(f"Not found: {raw}") from None
        if not (path.is_file() or path.is_dir()):
            raise LocalSourceError(f"Not a file or folder: {raw}")
        roots[path] = None
    return list(roots)


def availability_dirs(roots: Iterable[Path]) -> list[str]:
    """The folders whose presence a local import depends on: each folder root, and the
    folder holding each file root."""
    return list(dict.fromkeys(str(root if root.is_dir() else root.parent) for root in roots))


def _walk(top: Path) -> Iterator[os.DirEntry]:
    """Every regular file under ``top``, depth first in name order, without symlinks."""
    stack = [top]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue  # unreadable folder: skip it rather than fail the import
        subfolders = []
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                subfolders.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                yield entry
        stack.extend(reversed(subfolders))


def _local_file(path: Path, relative: str, stat: os.stat_result) -> LocalFile:
    return LocalFile(relative, path, stat.st_size, int(stat.st_mtime * 1000))


def list_root(root: Path) -> Iterator[LocalFile]:
    """The files under one root, with paths relative to the root's parent."""
    if root.is_file():
        yield _local_file(root, root.name, root.stat())
        return
    base = root.parent
    for entry in _walk(root):
        path = Path(entry.path)
        relative = normalise_relative_path(path.relative_to(base).as_posix())
        yield _local_file(path, relative, entry.stat(follow_symlinks=False))


def list_roots(roots: Iterable[Path], max_items: int) -> list[LocalFile]:
    """Every file under ``roots``, junk left out. Paths that collide across roots (two
    folders both called ``Maps``) get the later root's parent folder name in front.

    Raises ``TooManyLocalFilesError`` once more than ``max_items`` files are found.
    """
    files: list[LocalFile] = []
    taken: set[str] = set()
    for root in roots:
        for f in list_root(root):
            if is_os_junk(f.relative_path):
                continue
            relative = f.relative_path
            if relative in taken:
                relative = f"{root.parent.name}/{relative}"
            if relative in taken:
                continue
            taken.add(relative)
            files.append(LocalFile(relative, f.source_path, f.size, f.last_modified))
            if len(files) > max_items:
                raise TooManyLocalFilesError(max_items)
    return files


def add_local_items(
    db: Session,
    job: ImportJob,
    roots: list[Path],
    files: list[LocalFile],
    *,
    max_file_size: int,
    archive_limits: ArchiveLimits,
) -> LocalCounts:
    """Add ``files`` (``list_roots(roots)``, listed beforehand so the scan doesn't hold the
    write lock) to ``job`` as ready items read in place.

    Zips are expanded (reading them where they are; members go to staging, as for an
    uploaded zip). Validation is the manifest's: junk ignored, unsupported files skipped,
    oversized ones failed.
    """
    if job.planned_at is not None:
        raise ManifestSealedError(job.id)
    archives = [f for f in files if kind_for_path(f.relative_path) == "archive"]
    others = [f for f in files if kind_for_path(f.relative_path) != "archive"]

    taken = {path for (path,) in db.query(ImportItem.relative_path).filter_by(job_id=job.id)}
    new = [f for f in others if f.relative_path not in taken]
    counts = LocalCounts(ignored=len(others) - len(new))
    items = add_manifest_items(
        db,
        job,
        [
            ManifestEntry(f.relative_path, f.size, f.last_modified, source_path=str(f.source_path))
            for f in new
        ],
        max_file_size=max_file_size,
    )
    for item in items:
        _tally(counts, item.state)

    for archive in archives:
        result = expand_archive(
            db,
            job,
            archive.source_path,
            PurePosixPath(archive.relative_path).name,
            max_files=archive_limits.max_files,
            max_uncompressed_bytes=archive_limits.max_uncompressed_bytes,
            max_file_size=max_file_size,
            keep_source=True,
        )
        _add_archive_counts(counts, result)

    known = json.loads(job.source_roots) if job.source_roots else []
    job.source_roots = json.dumps(list(dict.fromkeys([*known, *availability_dirs(roots)])))
    db.flush()
    return counts


def _tally(counts: LocalCounts, state: str) -> None:
    if state == st.SKIPPED:
        counts.skipped += 1
    elif state == st.FAILED:
        counts.failed += 1
    else:
        counts.created += 1


def _add_archive_counts(counts: LocalCounts, result: ArchiveCounts) -> None:
    counts.created += result.created
    counts.skipped += result.skipped
    counts.failed += result.failed
