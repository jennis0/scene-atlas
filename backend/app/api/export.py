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
from datetime import UTC, datetime
from pathlib import Path

import zipstream
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload, selectinload

from ...pipeline.naming import export_metadata, unique_export_path
from ..config import settings
from ..models import Image
from ..services.originals import OriginalUnavailable, original_path
from .dependencies import get_db
from .rate_limits import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

_BATCH = 500
# ZIP local-file-header + data-descriptor overhead per entry (approximate)
_ZIP_ENTRY_OVERHEAD = 62


def _collect_entries(db: Session) -> tuple[list[tuple[str, Path]], dict]:
    """Query all images and build the list of (archive_path, source_path) pairs
    and the metadata dict.  Done in one pass so the DB session can be closed
    before we start streaming.
    """
    entries: list[tuple[str, Path]] = []
    metadata: dict[str, dict] = {}
    seen_paths: set[str] = set()
    skipped = 0

    offset = 0
    while True:
        batch = (
            db.query(Image)
            .options(
                joinedload(Image.tags), joinedload(Image.group), selectinload(Image.source_file)
            )
            .order_by(Image.id)
            .offset(offset)
            .limit(_BATCH)
            .all()
        )
        if not batch:
            break

        for img in batch:
            try:
                source = original_path(img)
            except OriginalUnavailable as exc:
                logger.warning("Export: skipped image %d: %s", img.id, exc.reason)
                skipped += 1
                continue

            arc = unique_export_path(img, seen_paths)

            entries.append((arc, source))

            metadata[arc] = export_metadata(img)

        offset += _BATCH

    if skipped:
        logger.warning("Export: skipped %d image(s) with missing files", skipped)

    return entries, metadata


def _build_zip(entries: list[tuple[str, Path]], metadata_bytes: bytes) -> zipstream.ZipStream:
    """Build a sized ZipStream (constant memory, lazy file reads).

    Using ``sized=True`` lets us call ``len(zs)`` for an exact Content-Length
    without manually computing ZIP overhead bytes.
    """
    zs = zipstream.ZipStream(compress_type=zipstream.ZIP_STORED, sized=True)

    # metadata.json first so it's easy to inspect without extracting images
    zs.add(metadata_bytes, "metadata.json")

    for arc_path, src_path in entries:
        zs.add_path(src_path, arcname=arc_path)

    return zs


@router.get("/library")
@limiter.limit(lambda: settings.rate_limit_expensive)
def export_library(request: Request, db: Session = Depends(get_db)):
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

    zs = _build_zip(entries, metadata_bytes)

    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="Scene Atlas Export.zip"',
            "Content-Length": str(len(zs)),
        },
    )
