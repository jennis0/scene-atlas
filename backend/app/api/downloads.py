"""Downloads of chosen groups and images (design/export-backup-move.md §5).

One endpoint serves every download of files: groups from the gallery and the group
editor, and several at once. Each is a zip of the originals in the readable layout
(``naming.ReadableLayout``) with a ``scene-atlas.jsonl`` (kind ``groups``) first, so the
zip re-imports with its names, groups, tags and grids. Single images are served by
``GET /images/{id}/file?download=1`` instead.

Downloads are capped (``MAX_FILES``, ``MAX_BYTES``) so any download re-imports as a zip
under the default import limits, and a dropped connection costs little: a single HTTP
download can't resume.

``POST /downloads/check`` takes JSON and applies the limits, so the UI can show the
count and size and any refusal. ``POST /downloads`` is a form, so the browser streams the
response straight to disk; a form POST is a request any site can send, so it requires a
same-origin request.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from urllib.parse import quote

import zipstream
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ...pipeline import library_format as lf
from ...pipeline.naming import ReadableLayout, layout_segment
from ..config import settings
from ..models import Image, ImageGroup, TagCategory, listed_images
from ..services.originals import OriginalUnavailable, original_path
from .dependencies import get_db
from .rate_limits import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# One less than the default import's file limit (1000): the metadata file is a member too.
MAX_FILES = 999
# The default import's size limit (2 GiB), less room for the metadata file and the zip's
# own headers (about 6 KB per image with 1024-d vectors, generously rounded up).
MAX_BYTES = 2 * 1024**3 - 32 * 1024 * 1024
MAX_IDS = 10_000


class Selection(BaseModel):
    group_ids: list[int] = Field(default_factory=list, max_length=MAX_IDS)
    image_ids: list[int] = Field(default_factory=list, max_length=MAX_IDS)


class DownloadCheck(BaseModel):
    image_count: int
    bytes: int
    ok: bool
    reason: str | None = None


def _condition(selection: Selection) -> ColumnElement[bool]:
    return or_(Image.group_id.in_(selection.group_ids), Image.id.in_(selection.image_ids))


def _check(db: Session, selection: Selection) -> DownloadCheck:
    count, size = db.execute(
        select(func.count(Image.id), func.coalesce(func.sum(Image.file_size), 0)).where(
            listed_images(), _condition(selection)
        )
    ).one()
    size = int(size or 0)
    reason = None
    if count == 0:
        reason = "Nothing to download"
    elif count > MAX_FILES:
        reason = f"That's {count:,} images; download at most {MAX_FILES:,} at a time"
    elif size > MAX_BYTES:
        reason = (
            f"That's {size / 1024**3:.1f} GB; download at most 2 GB at a time. "
            "To copy everything, use Settings → Library → Export library."
        )
    return DownloadCheck(image_count=count, bytes=size, ok=reason is None, reason=reason)


@router.post("/check", response_model=DownloadCheck)
def check_download(selection: Selection, db: Session = Depends(get_db)):
    """How many images and bytes a download would be, and whether it's allowed."""
    return _check(db, selection)


def _ids(raw: str) -> list[int]:
    try:
        ids = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="ids must be comma-separated numbers") from None
    if len(ids) > MAX_IDS:
        raise HTTPException(status_code=422, detail="Too many ids")
    return ids


def _require_same_origin(request: Request) -> None:
    """Refuse a form POST sent by a page on another site."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        if site not in ("same-origin", "none"):
            raise HTTPException(status_code=403, detail="Cross-site request refused")
        return
    origin = request.headers.get("origin")
    if origin is not None and origin.split("://", 1)[-1] != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Cross-site request refused")


def _zip_name(groups: Sequence[ImageGroup | None], count: int) -> str:
    named = [g for g in groups if g is not None]
    if len(groups) == 1 and named:
        group = named[0]
        stem = "_".join(
            p for p in (layout_segment(group.author), layout_segment(group.base_name)) if p
        )
        return f"{stem[:100] or 'scene-atlas-download'}.zip"
    return f"scene-atlas-download-{count}-images.zip"


@router.post("")
@limiter.limit(lambda: settings.rate_limit_expensive)
def download(
    request: Request,
    group_ids: str = Form(""),
    image_ids: str = Form(""),
    db: Session = Depends(get_db),
):
    """The chosen groups and images as a zip, with ``scene-atlas.jsonl`` first. Images
    whose original is missing or offline are left out (files and metadata alike)."""
    _require_same_origin(request)
    selection = Selection(group_ids=_ids(group_ids), image_ids=_ids(image_ids))
    checked = _check(db, selection)
    if not checked.ok:
        raise HTTPException(status_code=413 if checked.image_count else 404, detail=checked.reason)

    # The originals there are; the rest are left out, and logged
    sources: dict[int, str] = {}
    candidates = db.scalars(
        select(Image)
        .options(selectinload(Image.source_file))
        .where(listed_images(), _condition(selection))
    ).all()
    for img in candidates:
        try:
            sources[img.id] = str(original_path(img))
        except OriginalUnavailable as exc:
            logger.warning("Download: left out image %d: %s", img.id, exc.reason)
    if not sources:
        raise HTTPException(status_code=404, detail="None of those images' files can be read")

    from ...pipeline.metadata_export import model_info
    from ..services.lancedb_service import get_lancedb_service

    vectors = get_lancedb_service()
    order = {
        name: rank
        for rank, name in enumerate(
            db.scalars(
                select(TagCategory.name).order_by(TagCategory.display_order, TagCategory.name)
            )
        )
    }
    layout = ReadableLayout()
    groups_seen: list[ImageGroup | None] = []
    members: list[tuple[str, str]] = []  # (path in the zip, file on disk)

    def place(group: ImageGroup | None, images: Sequence[Image]) -> list[str]:
        groups_seen.append(group)
        paths = layout.place_images(group, images, order)
        members.extend((path, sources[img.id]) for img, path in zip(images, paths, strict=True))
        return paths

    header = lf.header_line(
        db,
        kind=lf.KIND_GROUPS,
        app_version=settings.app_version,
        library_id=None,
        model=model_info(vectors),
    )
    lines = [lf.dump_line(header)]
    lines.extend(
        lf.dump_line(line)
        for line in lf.group_lines(
            db,
            kind=lf.KIND_GROUPS,
            vectors=lambda ids: vectors.get_vectors(list(ids)),
            condition=Image.id.in_(list(sources)),
            place=place,
        )
    )

    zs = zipstream.ZipStream(compress_type=zipstream.ZIP_STORED, sized=True)
    zs.add("".join(lines).encode("utf-8"), lf.FILENAME)
    for arcname, source in members:
        zs.add_path(source, arcname=arcname)
    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={
            "Content-Disposition": attachment(_zip_name(groups_seen, len(members))),
            "Content-Length": str(len(zs)),
            "X-Accel-Buffering": "no",
        },
    )


def attachment(filename: str) -> str:
    """``Content-Disposition`` for *filename*, which may not be ASCII (RFC 6266)."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "'")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
