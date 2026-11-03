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
count, the size, the files that can't be read and any refusal. ``POST /downloads`` is a
form, so the browser streams the response straight to disk; a form POST is a request any
site can send, so it requires a same-origin request. The app submits it into a hidden
frame of its own (``lib/download.ts:postForDownload``), so an error can't replace the app:
error responses are plain text the frame may show (``X-Frame-Options: SAMEORIGIN``, where
every other response is ``DENY``), which the app reads and shows as a message.

No rate limit: a download costs disk reads, which a request rate doesn't bound, and a user
downloading a few groups in a row must not be refused.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import zipstream
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ...pipeline import library_format as lf
from ...pipeline.naming import ReadableLayout, layout_segment
from ..config import settings
from ..models import Image, ImageGroup, TagCategory, listed_images
from ..services.originals import OriginalUnavailable, original_path
from .dependencies import get_db
from .responses import attachment

logger = logging.getLogger(__name__)

router = APIRouter()

# One less than the default import's file limit (1000): the metadata file is a member too.
MAX_FILES = 999
# The default import's size limit (2 GiB): the whole zip must fit, so the files get that
# less room for the metadata file and the zip's own headers (about 6 KB per image with
# 1024-d vectors, generously rounded up). The zip itself is checked exactly.
MAX_ZIP_BYTES = 2 * 1024**3
MAX_BYTES = MAX_ZIP_BYTES - 32 * 1024 * 1024
MAX_IDS = 10_000


class Selection(BaseModel):
    group_ids: list[int] = Field(default_factory=list, max_length=MAX_IDS)
    image_ids: list[int] = Field(default_factory=list, max_length=MAX_IDS)


class DownloadCheck(BaseModel):
    image_count: int  # the images whose files can be read: what the zip will hold
    bytes: int
    missing: int  # images whose original is missing or offline: left out
    ok: bool
    reason: str | None = None


def _condition(selection: Selection) -> ColumnElement[bool]:
    return or_(Image.group_id.in_(selection.group_ids), Image.id.in_(selection.image_ids))


def _resolve(db: Session, selection: Selection) -> tuple[DownloadCheck, dict[int, Path]]:
    """The check, and the files of the images that can be read (image id → file)."""
    count = db.scalar(select(func.count(Image.id)).where(listed_images(), _condition(selection)))
    if not count:
        return DownloadCheck(
            image_count=0, bytes=0, missing=0, ok=False, reason="Nothing to download"
        ), {}
    if count > MAX_FILES:
        reason = f"That's {count:,} images; download at most {MAX_FILES:,} at a time"
        return DownloadCheck(image_count=count, bytes=0, missing=0, ok=False, reason=reason), {}
    sources: dict[int, Path] = {}
    size = missing = 0
    images = db.scalars(
        select(Image)
        .options(selectinload(Image.source_file))
        .where(listed_images(), _condition(selection))
    )
    for img in images:
        try:
            path = original_path(img)
            size += path.stat().st_size  # the file as it is now, not as imported
        except (OriginalUnavailable, OSError):
            missing += 1
            continue
        sources[img.id] = path
    reason = None
    if not sources:
        reason = "None of those images' files can be read"
    elif size > MAX_BYTES:
        reason = (
            f"That's {size / 1024**3:.1f} GB; download at most 2 GB at a time. "
            "To copy everything, use Settings → Library → Export library."
        )
    check = DownloadCheck(
        image_count=len(sources), bytes=size, missing=missing, ok=reason is None, reason=reason
    )
    return check, sources


@router.post("/check", response_model=DownloadCheck)
def check_download(selection: Selection, db: Session = Depends(get_db)):
    """How many images and bytes a download would be, how many files can't be read, and
    whether it's allowed."""
    return _resolve(db, selection)[0]


def _ids(raw: str) -> list[int]:
    try:
        ids = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise _Refused(422, "ids must be comma-separated numbers") from None
    if len(ids) > MAX_IDS:
        raise _Refused(422, "Too many ids")
    return ids


def _require_same_origin(request: Request) -> None:
    """Refuse a form POST sent by a page on another site."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        if site not in ("same-origin", "none"):
            raise _Refused(403, "Cross-site request refused")
        return
    origin = request.headers.get("origin")
    if origin is not None and origin.split("://", 1)[-1] != request.headers.get("host"):
        raise _Refused(403, "Cross-site request refused")


def _zip_name(groups: Sequence[ImageGroup | None], count: int) -> str:
    named = [g for g in groups if g is not None]
    if len(groups) == 1 and named:
        group = named[0]
        stem = "_".join(
            p for p in (layout_segment(group.author), layout_segment(group.base_name)) if p
        )
        return f"{stem[:100] or 'scene-atlas-download'}.zip"
    return f"scene-atlas-download-{count}-images.zip"


def tag_category_order(db: Session) -> dict[str, int]:
    """Category → rank, the order tags go in readable names (as Settings lists them)."""
    names = db.scalars(
        select(TagCategory.name).order_by(TagCategory.display_order, TagCategory.name)
    )
    return {name: rank for rank, name in enumerate(names)}


class _Refused(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _error(status: int, detail: str) -> PlainTextResponse:
    """An error the app's hidden download frame may show (plain text, which every browser
    shows as it is), so the app can read it and say what went wrong."""
    return PlainTextResponse(detail, status_code=status, headers={"X-Frame-Options": "SAMEORIGIN"})


@router.post("")
def download(
    request: Request,
    group_ids: str = Form(""),
    image_ids: str = Form(""),
    db: Session = Depends(get_db),
):
    """The chosen groups and images as a zip, with ``scene-atlas.jsonl`` first. Images
    whose original is missing or offline are left out (files and metadata alike)."""
    try:
        return _download(request, group_ids, image_ids, db)
    except _Refused as e:
        return _error(e.status, e.detail)
    except Exception:
        logger.exception("Download failed")
        return _error(500, "The download couldn't be made; see the log")


def _download(request: Request, group_ids: str, image_ids: str, db: Session) -> StreamingResponse:
    _require_same_origin(request)
    selection = Selection(group_ids=_ids(group_ids), image_ids=_ids(image_ids))
    checked, sources = _resolve(db, selection)
    if not checked.ok:
        raise _Refused(413 if checked.image_count else 404, checked.reason or "Nothing to download")

    from ...pipeline.metadata_export import model_info
    from ..services.lancedb_service import get_lancedb_service

    service = get_lancedb_service()
    vectors = service.get_vectors(list(sources))  # one scan of the table, not one per group
    order = tag_category_order(db)
    layout = ReadableLayout()
    groups_seen: list[ImageGroup | None] = []
    members: list[tuple[str, Path]] = []  # (path in the zip, file on disk)

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
        model=model_info(service),
    )
    lines = [lf.dump_line(header)]
    lines.extend(
        lf.dump_line(line)
        for line in lf.group_lines(
            db,
            kind=lf.KIND_GROUPS,
            vectors=lambda ids: {i: vectors[i] for i in ids if i in vectors},
            condition=Image.id.in_(list(sources)),
            place=place,
        )
    )

    zs = zipstream.ZipStream(compress_type=zipstream.ZIP_STORED, sized=True)
    zs.add("".join(lines).encode("utf-8"), lf.FILENAME)
    for arcname, source in members:
        zs.add_path(str(source), arcname=arcname)
    if len(zs) > MAX_ZIP_BYTES:  # exact, with the metadata and the zip's own headers
        raise _Refused(413, "That's over 2 GB once zipped; download fewer at a time")
    # A file deleted between here and the stream cuts the response short of its length:
    # the browser reports the download failed, which is what happened.
    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={
            "Content-Disposition": attachment(_zip_name(groups_seen, len(members))),
            "Content-Length": str(len(zs)),
            "X-Accel-Buffering": "no",
        },
    )
