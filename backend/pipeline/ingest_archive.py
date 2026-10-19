"""Expand an uploaded zip into import items (ADR-018, design/ingestion.md §7).

Archives are expanded before the manifest is sealed, so their contents are
grouped together with everything else. Each supported member is extracted to a
server-generated staging name, hashed while extracting, checked against its
claimed type, and becomes an item with its bytes already received.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from sqlalchemy.orm import Session

from backend.app.models import ImportItem, ImportJob
from backend.app.services import ingest_state as st
from backend.app.services.image_parser import ImageParser
from backend.app.services.ingest_state import ItemEvent
from backend.app.services.validation import check_zip_safety, verify_media_mime

from .error_classifier import KIND_FILE
from .ingest_queue import (
    ManifestSealedError,
    is_os_junk,
    kind_for_path,
    mark_bytes_received,
    normalise_relative_path,
    staging_dir_for,
)

logger = logging.getLogger(__name__)

_COPY_CHUNK = 1024 * 1024


@dataclass
class ArchiveCounts:
    created: int = 0
    skipped: int = 0
    failed: int = 0


def _new_item(job: ImportJob, relative_path: str, kind: str, size: int | None) -> ImportItem:
    return ImportItem(
        job_id=job.id,
        kind=kind,
        relative_path=relative_path,
        filename=PurePosixPath(relative_path).name,
        size=size,
        image_type=job.default_image_type,
        state=st.AWAITING_BYTES,
    )


def _settle(item: ImportItem, event: ItemEvent, reason: str, *, kind: str | None = None) -> None:
    item.state = st.next_item_state(item.state, event)
    item.error_stage = "validate"
    item.error_reason = reason
    item.error_kind = kind


@cache
def _folder_parser() -> ImageParser:
    return ImageParser()


def _strip_name_copies(parts: list[str], zip_stem: str) -> list[str]:
    """Drop leading folders that repeat the zip's name ("Golden Forest/" in Golden Forest.zip)."""
    while len(parts) > 1 and _folder_parser().same_name(parts[0], zip_stem):
        parts = parts[1:]
    return parts


def place_members(paths: list[str], archive_name: str) -> dict[str, str]:
    """Map member paths (normalised) to the relative paths their items get.

    A zip whose media sit at its root, or only in folders that add nothing to its name
    (Gridded, VTT, or a copy of the zip's name), is one pack named after the zip: its
    members go under ``<zip's folder>/<zip stem>/``, as if it had been extracted there,
    minus any copy of the name. Otherwise its own folders name things, and members keep
    their paths inside the zip. See design/ingestion.md §7.
    """
    archive = PurePosixPath(archive_name)
    zip_stem = archive.stem
    parser = _folder_parser()
    stripped = {path: _strip_name_copies(path.split("/"), zip_stem) for path in paths}
    media_folders = {
        folder
        for path, parts in stripped.items()
        if kind_for_path(path) in ("image", "video")
        for folder in parts[:-1]
    }
    if not all(parser.is_generic_folder(f) or parser.same_name(f, zip_stem) for f in media_folders):
        return {path: path for path in paths}
    prefix = PurePosixPath(archive.parent, zip_stem)
    return {path: str(PurePosixPath(prefix, *parts)) for path, parts in stripped.items()}


def _extract(zf: ZipFile, member, dest: Path) -> str:
    """Extract one member to ``dest`` (via a temp name), returning its SHA-256."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with zf.open(member) as src, open(tmp, "wb") as out:
            while chunk := src.read(_COPY_CHUNK):
                digest.update(chunk)
                out.write(chunk)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return digest.hexdigest()


def expand_archive(
    db: Session,
    job: ImportJob,
    zip_path: Path,
    name: str,
    *,
    max_files: int,
    max_uncompressed_bytes: int,
    max_file_size: int,
    keep_source: bool = False,
) -> ArchiveCounts:
    """Turn the zip at ``zip_path`` into items of ``job``. Deletes ``zip_path`` afterwards
    unless ``keep_source`` (a local import reads the user's own zip in place).

    - A zip that fails the safety check becomes one failed ``archive`` item.
    - ``name`` is the zip's relative path, folders included where known.
    - Members are placed by ``place_members``; if a path collides with one
      already in the job, it's prefixed with the zip's name.
    - OS junk is ignored; unsupported files and nested archives are skipped.
    """
    if job.planned_at is not None:
        raise ManifestSealedError(job.id)

    counts = ArchiveCounts()
    archive_name = normalise_relative_path(name) or "archive.zip"
    zip_stem = PurePosixPath(archive_name).stem
    try:
        try:
            check_zip_safety(
                zip_path, max_files=max_files, max_uncompressed_bytes=max_uncompressed_bytes
            )
        except ValueError as exc:
            item = _new_item(job, archive_name, "archive", zip_path.stat().st_size)
            _settle(item, ItemEvent.FILE_ERROR, str(exc), kind=KIND_FILE)
            db.add(item)
            counts.failed += 1
            return counts

        taken = {path for (path,) in db.query(ImportItem.relative_path).filter_by(job_id=job.id)}
        staging = staging_dir_for(job.id)
        staging.mkdir(parents=True, exist_ok=True)

        with ZipFile(zip_path) as zf:
            members = []
            for member in zf.infolist():
                if member.is_dir():
                    continue
                path = normalise_relative_path(member.filename)
                if path and not is_os_junk(path):
                    members.append((member, path))
            placed = place_members([path for _, path in members], archive_name)
            for member, member_path in members:
                path = placed[member_path]
                if path in taken:
                    path = f"{zip_stem}/{path}"
                if path in taken:
                    continue
                taken.add(path)

                kind = kind_for_path(path)
                item = _new_item(job, path, kind or "image", member.file_size)
                db.add(item)
                if kind is None or kind == "archive":
                    reason = (
                        "Archives inside archives aren't expanded"
                        if kind == "archive"
                        else "Not a supported image, video or archive"
                    )
                    _settle(item, ItemEvent.SKIP, reason)
                    counts.skipped += 1
                    continue
                if member.file_size > max_file_size:
                    _settle(
                        item,
                        ItemEvent.FILE_ERROR,
                        "File is larger than the import size limit",
                        kind=KIND_FILE,
                    )
                    counts.failed += 1
                    continue

                ext = PurePosixPath(path).suffix.lower()
                staging_key = f"{uuid.uuid4().hex}{ext}"
                dest = staging / staging_key
                source_hash = _extract(zf, member, dest)
                if not verify_media_mime(dest, ext):
                    dest.unlink(missing_ok=True)
                    _settle(
                        item,
                        ItemEvent.FILE_ERROR,
                        "File content doesn't match its type",
                        kind=KIND_FILE,
                    )
                    counts.failed += 1
                    continue
                mark_bytes_received(db, item, staging_key=staging_key, source_hash=source_hash)
                counts.created += 1
        db.flush()
        return counts
    finally:
        if not keep_source:
            zip_path.unlink(missing_ok=True)
