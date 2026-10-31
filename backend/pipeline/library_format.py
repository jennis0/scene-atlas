"""The ``scene-atlas.jsonl`` format (design/export-backup-move.md §2).

One JSON object per line: a header, then one line per gallery group with its images
(``"group": null`` for ungrouped images), and in ``library`` files ``source_files`` lines
for the linked library. Written and read a line at a time, so a 200k-image library never
has to fit in memory.

- ``kind = "library"``: a metadata export. Carries ids, storage keys and settings, so a
  rebuild can recreate the database exactly.
- ``kind = "groups"``: written beside files (a download, the full export, a set-aside
  folder). Carries each file's ``path`` instead.

The reader validates every line: the file is untrusted input.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.database import (
    AppSetting,
    Image,
    ImageGroup,
    SourceFile,
    TagCategory,
    listed_images,
)

FORMAT = "scene-atlas"
VERSION = "1.0"
MAJOR = 1
FILENAME = "scene-atlas.jsonl"
KIND_LIBRARY = "library"
KIND_GROUPS = "groups"

# A line longer than this is refused before it is parsed. A group line holds its images,
# vectors included (about 5.5 KB each for a 1024-d model), so this allows ~10k per group.
MAX_LINE_BYTES = 64 * 1024 * 1024
_GROUP_BATCH = 500
_SOURCE_FILE_BATCH = 2_000

VectorLookup = Callable[[Sequence[int]], Mapping[int, Sequence[float]]]
"""Image id → embedding, for the ids asked for. Raises on a read error: an export must
not silently leave vectors out."""


class FormatError(ValueError):
    """A line that isn't valid ``scene-atlas.jsonl``. ``line`` is 1-based."""

    def __init__(self, line: int, message: str):
        super().__init__(f"Line {line}: {message}")
        self.line = line


# Validation. Limits are generous: they stop hostile input, not unusual libraries.

Text = Annotated[str, StringConstraints(max_length=1_000)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# Store and thumbnail keys are file names in the store's shards: never a path.
Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,199}$")]


class _Entry(BaseModel):
    # Fields a newer minor version adds are ignored, not refused.
    model_config = ConfigDict(extra="ignore")


class ModelInfo(_Entry):
    name: Name
    encoder_sha256: Hash | None = None
    dim: int = Field(ge=1, le=8192)


TagValue = Annotated[str, StringConstraints(max_length=200)]


class CommonValue(_Entry):
    """A tag category's value with its aliases (``vocabulary.build_common_values_json``)."""

    value: TagValue
    aliases: list[TagValue] = Field(default_factory=list, max_length=100)


class TagCategoryEntry(_Entry):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    description: Text | None = None
    color: Annotated[str, StringConstraints(max_length=50)] | None = None
    icon: Annotated[str, StringConstraints(max_length=50)] | None = None
    # Plain strings, or a value with its aliases
    common_values: list[TagValue | CommonValue] = Field(default_factory=list, max_length=1_000)
    display_order: int = 0


class Header(_Entry):
    format: Literal["scene-atlas"]
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+$")]
    kind: Literal["library", "groups"]
    app_version: Annotated[str, StringConstraints(max_length=50)]
    library_id: Annotated[str, StringConstraints(max_length=100)] | None = None
    created_at: datetime
    model: ModelInfo | None = None
    tag_categories: list[TagCategoryEntry] = Field(default_factory=list, max_length=1_000)
    settings: dict[str, Any] | None = None


class TagEntry(_Entry):
    category: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    value: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    source: Annotated[str, StringConstraints(max_length=20)] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class GridEntry(_Entry):
    gridded: bool | None = None
    type: Literal["square", "hex"] | None = None
    width: int | None = Field(default=None, ge=1, le=10_000)
    height: int | None = Field(default=None, ge=1, le=10_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["filename", "detector", "user"] | None = None


class ImageEntry(_Entry):
    id: int | None = Field(default=None, ge=1)  # library files
    filename: Text
    name: Text | None = None
    author: Text | None = None
    subgroup: Text | None = None
    image_type: Literal["battlemap", "scene"]
    media_type: Literal["image", "video"] = "image"
    created_at: datetime | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    file_size: int | None = Field(default=None, ge=0)
    grid: GridEntry = Field(default_factory=GridEntry)
    tags: list[TagEntry] = Field(default_factory=list, max_length=500)
    stored_hash: Hash | None = None
    content_hash: Hash | None = None
    pixel_hash: Hash | None = None
    phash: int | None = None
    colors: list[tuple[Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")], float]] = (
        Field(default_factory=list, max_length=64)
    )
    vector: Annotated[str, StringConstraints(max_length=50_000)] | None = None
    path: Annotated[str, StringConstraints(max_length=1_000)] | None = None  # groups files
    storage_key: Key | None = None  # library files, from here on
    thumbnail_key: Key | None = None
    source_file_id: int | None = Field(default=None, ge=1)
    missing_since: datetime | None = None


class GroupEntry(_Entry):
    id: int | None = Field(default=None, ge=1)  # library files
    uid: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    base_name: Name
    author: Text | None = None
    created_at: datetime | None = None
    primary: int | None = Field(default=None, ge=0)  # index into the line's images


class GroupLine(_Entry):
    group: GroupEntry | None
    images: list[ImageEntry] = Field(min_length=1, max_length=100_000)


class SourceFileEntry(_Entry):
    id: int = Field(ge=1)
    rel_key: Annotated[str, StringConstraints(min_length=1, max_length=4_096)]
    size: int = Field(ge=0)
    mtime_ns: int
    content_hash: Hash | None = None
    state: Literal["pending", "image", "duplicate", "skipped", "failed", "removed"]
    image_id: int | None = Field(default=None, ge=1)
    reason: Text | None = None
    missing_since: datetime | None = None


class SourceFilesLine(_Entry):
    source_files: list[SourceFileEntry] = Field(min_length=1, max_length=100_000)


Line = Header | GroupLine | SourceFilesLine


# Vectors


def encode_vector(vector: Sequence[float] | np.ndarray) -> str:
    """Base64 of little-endian float32."""
    return base64.b64encode(np.asarray(vector, dtype="<f4").tobytes()).decode("ascii")


def decode_vector(text: str, dim: int) -> np.ndarray:
    """The embedding *text* encodes. Raises ``ValueError`` if it isn't *dim* floats."""
    raw = base64.b64decode(text, validate=True)
    if len(raw) != dim * 4:
        raise ValueError(f"vector has {len(raw) // 4} values, expected {dim}")
    return np.frombuffer(raw, dtype="<f4").copy()


# Writing


def dump_line(obj: Mapping[str, Any]) -> str:
    """One line of the file, newline included."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_json_default) + "\n"


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def header_line(
    db: Session,
    *,
    kind: str,
    app_version: str,
    library_id: str | None,
    model: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The header: format, version and kind, the model whose vectors follow, the tag
    categories, and (``library`` only) every app setting."""
    categories = db.scalars(
        select(TagCategory).order_by(TagCategory.display_order, TagCategory.name)
    )
    header: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "kind": kind,
        "app_version": app_version,
        "library_id": library_id,
        "created_at": datetime.now(UTC),
        "model": dict(model) if model else None,
        "tag_categories": [
            {
                "name": c.name,
                "description": c.description,
                "color": c.color,
                "icon": c.icon,
                "common_values": json.loads(c.common_values) if c.common_values else [],
                "display_order": c.display_order or 0,
            }
            for c in categories
        ],
    }
    if kind == KIND_LIBRARY:
        header["settings"] = {
            s.key: json.loads(s.value_json) if s.value_json is not None else None
            for s in db.scalars(select(AppSetting).order_by(AppSetting.key))
        }
    return header


def _image_query(condition: ColumnElement[bool] | None):
    query = (
        select(Image)
        .options(selectinload(Image.tags), selectinload(Image.colors))
        .where(listed_images())
        .order_by(Image.id)
    )
    return query.where(condition) if condition is not None else query


def iter_groups(
    db: Session, condition: ColumnElement[bool] | None = None
) -> Iterator[tuple[ImageGroup | None, list[Image]]]:
    """Each group with its listed images (matching *condition*, a filter on ``Image``), in
    group-id order, then the ungrouped images in batches as ``(None, images)``. Images are
    in id order. Images still awaiting grouping are left out."""
    after = 0
    while True:
        groups = db.scalars(
            select(ImageGroup)
            .where(ImageGroup.id > after)
            .order_by(ImageGroup.id)
            .limit(_GROUP_BATCH)
        ).all()
        if not groups:
            break
        after = groups[-1].id
        by_group: dict[int, list[Image]] = {}
        query = _image_query(condition).where(Image.group_id.in_([g.id for g in groups]))
        for img in db.scalars(query):
            by_group.setdefault(img.group_id or 0, []).append(img)
        for group in groups:
            if group.id in by_group:
                yield group, by_group[group.id]
    after = 0
    while True:
        query = _image_query(condition).where(Image.group_id.is_(None), Image.id > after)
        images = list(db.scalars(query.limit(_GROUP_BATCH)))
        if not images:
            break
        after = images[-1].id
        yield None, images


def image_entry(
    img: Image, *, kind: str, path: str | None = None, vector: Sequence[float] | None = None
) -> dict[str, Any]:
    """The line entry for *img*."""
    entry: dict[str, Any] = {
        "filename": img.filename,
        "name": img.name,
        "author": img.author,
        "subgroup": img.subgroup,
        "image_type": img.image_type or "battlemap",
        "media_type": img.media_type or "image",
        "created_at": img.created_at,
        "width": img.width,
        "height": img.height,
        "file_size": img.file_size,
        "grid": {
            "gridded": img.gridded,
            "type": img.grid_type,
            "width": img.grid_width,
            "height": img.grid_height,
            "confidence": img.grid_confidence,
            "source": img.grid_source,
        },
        "tags": [
            {
                "category": t.category,
                "value": t.value,
                "source": t.source,
                "confidence": t.confidence,
            }
            for t in img.tags
        ],
        # The hash of the stored file: the bytes an export contains. Older rows lack it.
        "stored_hash": img.stored_hash or img.content_hash,
        "content_hash": img.content_hash,
        "pixel_hash": img.pixel_hash,
        "phash": img.phash,
        "colors": [
            [c.color_hex, c.percentage or 0.0]
            for c in sorted(img.colors, key=lambda c: c.color_order or 0)
        ],
        "vector": encode_vector(vector) if vector is not None else None,
    }
    if kind == KIND_LIBRARY:
        entry |= {
            "id": img.id,
            "storage_key": img.storage_key,
            "thumbnail_key": img.thumbnail_key,
            "source_file_id": img.source_file_id,
        }
    else:
        entry["path"] = path
    return entry


def group_entry(group: ImageGroup, images: Sequence[Image], *, kind: str) -> dict[str, Any]:
    """The ``group`` of a line."""
    ids = [img.id for img in images]
    entry: dict[str, Any] = {
        "uid": group.uid,
        "base_name": group.base_name,
        "author": group.author,
        "created_at": group.created_at,
        "primary": ids.index(group.primary_image_id) if group.primary_image_id in ids else None,
    }
    if kind == KIND_LIBRARY:
        entry["id"] = group.id
    return entry


def group_lines(
    db: Session,
    *,
    kind: str,
    vectors: VectorLookup | None = None,
    condition: ColumnElement[bool] | None = None,
    place: Callable[[ImageGroup | None, Sequence[Image]], Sequence[str]] | None = None,
) -> Iterator[dict[str, Any]]:
    """A line per group (``iter_groups``). *place* gives each image's path in ``groups``
    files; *vectors* fills in embeddings."""
    for group, images in iter_groups(db, condition):
        found = vectors([img.id for img in images]) if vectors else {}
        paths = place(group, images) if place else [None] * len(images)
        yield {
            "group": group_entry(group, images, kind=kind) if group else None,
            "images": [
                image_entry(img, kind=kind, path=path, vector=found.get(img.id))
                for img, path in zip(images, paths, strict=True)
            ],
        }


def source_file_lines(db: Session) -> Iterator[dict[str, Any]]:
    """Every ``source_files`` row, in batches."""
    after = 0
    while True:
        rows = db.scalars(
            select(SourceFile)
            .where(SourceFile.id > after)
            .order_by(SourceFile.id)
            .limit(_SOURCE_FILE_BATCH)
        ).all()
        if not rows:
            return
        after = rows[-1].id
        yield {
            "source_files": [
                {
                    "id": r.id,
                    "rel_key": r.rel_key,
                    "size": r.size,
                    "mtime_ns": r.mtime_ns,
                    "content_hash": r.content_hash,
                    "state": r.state,
                    "image_id": r.image_id,
                    "reason": r.reason,
                    "missing_since": r.missing_since,
                }
                for r in rows
            ]
        }


def library_lines(
    db: Session,
    *,
    app_version: str,
    library_id: str | None,
    model: Mapping[str, Any] | None,
    vectors: VectorLookup | None,
) -> Iterator[str]:
    """Every line of a ``library`` file (a metadata export), as text."""
    yield dump_line(
        header_line(
            db, kind=KIND_LIBRARY, app_version=app_version, library_id=library_id, model=model
        )
    )
    for line in group_lines(db, kind=KIND_LIBRARY, vectors=vectors):
        yield dump_line(line)
    for line in source_file_lines(db):
        yield dump_line(line)


# Reading


def open_file(path: Path) -> io.TextIOWrapper:
    """*path* as text, gunzipped if it is gzip."""
    with path.open("rb") as probe:
        gzipped = probe.read(2) == b"\x1f\x8b"
    if gzipped:
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _raw_lines(fp: io.TextIOBase) -> Iterator[tuple[int, str]]:
    number = 0
    while True:
        text = fp.readline(MAX_LINE_BYTES + 1)
        if not text:
            return
        number += 1
        if len(text) > MAX_LINE_BYTES:
            raise FormatError(number, "line is too long")
        if text.strip():
            yield number, text


def read_lines(fp: io.TextIOBase | Iterable[str]) -> Iterator[Line]:
    """Every line of a file, validated: the ``Header`` first, then ``GroupLine`` and
    ``SourceFilesLine`` objects. Lines of a kind this version doesn't know are skipped.
    Raises ``FormatError`` at the first invalid line."""
    raw = _raw_lines(fp) if isinstance(fp, io.TextIOBase) else enumerate(fp, start=1)
    header: Header | None = None
    for number, text in raw:
        if not text.strip():
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            raise FormatError(number, f"not JSON ({e.msg})") from None
        if not isinstance(obj, dict):
            raise FormatError(number, "not a JSON object")
        try:
            if header is None:
                header = Header.model_validate(obj)
                if int(header.version.split(".")[0]) != MAJOR:
                    raise FormatError(number, f"version {header.version} is not supported")
                yield header
            elif "images" in obj:
                yield GroupLine.model_validate(obj)
            elif "source_files" in obj:
                yield SourceFilesLine.model_validate(obj)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise FormatError(
                number, f"{where}: {first['msg']}" if where else first["msg"]
            ) from None
    if header is None:
        raise FormatError(1, "the file is empty")
