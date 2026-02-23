"""Library export endpoint.

Streams the entire image library as a ZIP archive, organised into a
human-readable folder structure:

    Author/
      Group/
        [Subgroup/]
          Group - [Subgroup - ]Name - Grid WxH.ext
      _Ungrouped/
        Name - No Grid.ext

A ``metadata.json`` file is included as the first entry in the archive.

The response is streamed using ``zipstream-ng`` so memory usage stays
constant regardless of library size — only one file is read from disk
at a time.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import zipstream
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from ...pipeline.naming import export_path
from ..models import Image, get_session_local
from ..services import get_image_store

logger = logging.getLogger(__name__)

router = APIRouter()

_BATCH = 500
# ZIP local-file-header + data-descriptor overhead per entry (approximate)
_ZIP_ENTRY_OVERHEAD = 62


def get_db(request: Request):
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _collect_entries(db: Session) -> tuple[list[tuple[str, Path]], dict]:
    """Query all images and build the list of (archive_path, source_path) pairs
    and the metadata dict.  Done in one pass so the DB session can be closed
    before we start streaming.
    """
    image_store = get_image_store()
    entries: list[tuple[str, Path]] = []
    metadata: dict[str, dict] = {}
    seen_paths: set[str] = set()
    skipped = 0

    offset = 0
    while True:
        batch = (
            db.query(Image)
            .options(joinedload(Image.tags), joinedload(Image.group))
            .order_by(Image.id)
            .offset(offset)
            .limit(_BATCH)
            .all()
        )
        if not batch:
            break

        for img in batch:
            source = image_store.get_path(img.storage_key)
            if not source or not source.exists():
                logger.warning("Export: missing file for image %d (%s)", img.id, img.storage_key)
                skipped += 1
                continue

            group_name = img.group.base_name if img.group else None
            arc = export_path(img, group_name, img.author)

            # Deduplicate: append (2), (3) … before the extension
            if arc in seen_paths:
                stem = Path(arc).stem
                ext = Path(arc).suffix
                parent = str(Path(arc).parent)
                n = 2
                while True:
                    candidate = f"{parent}/{stem} ({n}){ext}"
                    if candidate not in seen_paths:
                        arc = candidate
                        break
                    n += 1
            seen_paths.add(arc)

            entries.append((arc, source))

            # Build tags dict: {category: [value, ...]}
            tags_by_cat: dict[str, list[str]] = defaultdict(list)
            for tag in img.tags:
                tags_by_cat[tag.category].append(tag.value)

            metadata[arc] = {
                "image_type": img.image_type or "battlemap",
                "gridded": bool(img.gridded),
                "grid_type": img.grid_type,
                "grid_width": img.grid_width,
                "grid_height": img.grid_height,
                "tags": dict(tags_by_cat),
            }

        offset += _BATCH

    if skipped:
        logger.warning("Export: skipped %d image(s) with missing files", skipped)

    return entries, metadata


def _content_length(entries: list[tuple[str, Path]], metadata_bytes: bytes) -> int:
    """Estimate the ZIP Content-Length for ZIP_STORED (no compression).

    For stored entries the size is predictable:
        local header (30) + filename + file data + data descriptor (16)
        central-dir entry (46) + filename  (one per file)
        end-of-central-dir record (22)
    """
    total = 0
    for arc, src in entries:
        name_len = len(arc.encode("utf-8"))
        file_size = src.stat().st_size
        total += 30 + name_len + file_size + 16  # local header + data + descriptor
        total += 46 + name_len  # central dir entry

    # metadata.json entry
    mj_name = b"metadata.json"
    mj_len = len(mj_name)
    total += 30 + mj_len + len(metadata_bytes) + 16
    total += 46 + mj_len

    total += 22  # end-of-central-dir record
    return total


def _stream_zip(entries: list[tuple[str, Path]], metadata_bytes: bytes):
    """Yield ZIP chunks using zipstream-ng (constant memory, lazy file reads)."""
    zs = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_STORED, allowZip64=True)

    # metadata.json first so it's easy to inspect without extracting images
    zs.write_iter("metadata.json", iter([metadata_bytes]))

    for arc_path, src_path in entries:
        zs.write(str(src_path), arcname=arc_path)

    yield from zs


@router.get("/library")
async def export_library(db: Session = Depends(get_db)):
    """Stream the entire image library as a ZIP archive.

    Memory usage is constant — images are read from disk one at a time.
    Set ``Content-Length`` so browsers can show a real download progress bar.
    """
    entries, metadata = _collect_entries(db)

    meta_payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": 1,
        "total_images": len(entries),
        "images": metadata,
    }
    metadata_bytes = json.dumps(meta_payload, indent=2, ensure_ascii=False).encode("utf-8")

    content_length = _content_length(entries, metadata_bytes)

    return StreamingResponse(
        _stream_zip(entries, metadata_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="Scene Atlas Export.zip"',
            "Content-Length": str(content_length),
        },
    )
