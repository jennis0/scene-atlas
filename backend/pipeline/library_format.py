"""The ``scene-atlas.jsonl`` format (design/export-backup-move.md §2).

One JSON object per line: a header, then the gallery groups with their images
(``"group": null`` for ungrouped images), and in ``library`` files ``source_files`` lines
for the linked library. Written and read a line at a time, so a 200k-image library never
has to fit in memory. A group with more than ``MAX_IMAGES_PER_LINE`` images spans several
lines with the same ``uid``; readers join them.

- ``kind = "library"``: a metadata export. Carries ids, storage keys and settings, so a
  rebuild can recreate the database exactly.
- ``kind = "groups"``: written beside files (a download, the full export, a set-aside
  folder). Carries each file's ``path`` instead.

The file is untrusted input, so the reader validates every line, but it accepts anything
the database can hold: an export must never be refused by its own reader. Values it can't
use (an unknown grid type, an out-of-range number, a malformed hash) become null, and
over-long text is cut short. Only what protects the reader or the filesystem is refused
outright: a line too long, a non-finite or out-of-range number where an id or size goes,
a storage key that isn't a plain name in the store. The writer passes every line through
the same models, so what it writes is exactly what the reader returns.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    model_validator,
)
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.database import (
    FILE_DUPLICATE,
    FILE_IMAGE,
    FILE_PENDING,
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

# A line longer than this (in characters) is refused before it is parsed.
MAX_LINE_CHARS = 64 * 1024 * 1024
# A group's images go on lines of at most this many: about 12 MB with 1024-d vectors.
MAX_IMAGES_PER_LINE = 2_000
_GROUP_BATCH = 500
_SOURCE_FILE_BATCH = 2_000
_INT64_MAX = 2**63 - 1  # SQLite's INTEGER

VectorLookup = Callable[[Sequence[int]], Mapping[int, Sequence[float] | np.ndarray]]
"""Image id → embedding, for the ids asked for. Raises on a read error: an export must
not silently leave vectors out."""


class FormatError(ValueError):
    """A line that isn't valid ``scene-atlas.jsonl``. ``line`` is 1-based."""

    def __init__(self, line: int, message: str):
        super().__init__(f"Line {line}: {message}")
        self.line = line


class ExportError(ValueError):
    """A database row the writer can't put in the file (it names the row)."""


# Validation


def _cut(limit: int) -> BeforeValidator:
    """Text longer than *limit* is cut short, not refused."""
    return BeforeValidator(lambda v: v[:limit] if isinstance(v, str) else v)


def _or_none(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    try:
        return handler(value)
    except ValidationError:
        return None


def _or_default(default: Any) -> WrapValidator:
    def validate(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        try:
            return handler(value)
        except ValidationError:
            return default

    return WrapValidator(validate)


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


OrNone = WrapValidator(_or_none)
Text = Annotated[str, _cut(4_000)]
Short = Annotated[str, _cut(200)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MaybeHash = Annotated[Hash | None, OrNone]
Id = Annotated[int, Field(ge=1, le=_INT64_MAX)]
Int64 = Annotated[int, Field(ge=-(2**63), le=_INT64_MAX)]
Count = Annotated[int, Field(ge=0, le=_INT64_MAX)]
Fraction = Annotated[float | None, Field(ge=0, le=1), OrNone]
_KEY = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,199}")


def _store_key(value: str) -> str:
    """A key in the store or thumbnail folder: plain names, optionally in ``/``-separated
    shard folders. Never absolute, never ``..``: a rebuild joins it to the store's root."""
    if len(value) > 255 or not all(_KEY.fullmatch(part) for part in value.split("/")):
        raise ValueError("not a store key")
    return value


Key = Annotated[str, AfterValidator(_store_key)]


class _Entry(BaseModel):
    # Fields a newer minor version adds are ignored, not refused. NaN and infinities are
    # refused wherever a number goes, which lenient fields then turn into null.
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class ModelInfo(_Entry):
    name: Short
    encoder_sha256: MaybeHash = None
    dim: int = Field(ge=1, le=8192)


class CommonValue(_Entry):
    """A tag category's value with its aliases (``vocabulary.build_common_values_json``)."""

    value: Short
    aliases: list[Short] = Field(default_factory=list, max_length=100)


class TagCategoryEntry(_Entry):
    name: Short
    description: Text | None = None
    color: Short | None = None
    icon: Short | None = None
    # Plain strings, or a value with its aliases
    common_values: list[Short | CommonValue] = Field(default_factory=list, max_length=10_000)
    display_order: Annotated[int, _or_default(0)] = 0


class Header(_Entry):
    format: Literal["scene-atlas"]
    version: Annotated[str, Field(pattern=r"^[0-9]{1,6}\.[0-9]{1,6}$")]
    kind: Literal["library", "groups"]
    app_version: Short
    library_id: Short | None = None
    created_at: datetime
    model: ModelInfo | None = None
    tag_categories: list[TagCategoryEntry] = Field(default_factory=list, max_length=10_000)
    settings: dict[str, Any] | None = None


class TagEntry(_Entry):
    category: Short
    value: Short
    source: Short | None = None
    confidence: Fraction = None


class GridEntry(_Entry):
    gridded: Annotated[bool | None, OrNone] = None
    type: Annotated[Literal["square", "hex"] | None, BeforeValidator(_lower), OrNone] = None
    width: Annotated[int | None, Field(ge=1, le=100_000), OrNone] = None
    height: Annotated[int | None, Field(ge=1, le=100_000), OrNone] = None
    confidence: Fraction = None
    source: Annotated[Literal["filename", "detector", "user"] | None, OrNone] = None


def _colors(value: Any) -> Any:
    """Keep the ``[hex, percentage]`` pairs that are usable; drop the rest."""
    if not isinstance(value, list):
        return []
    kept = []
    for item in value[:64]:
        if (
            isinstance(item, list | tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and re.fullmatch(r"#[0-9A-Fa-f]{6}", item[0])
            and isinstance(item[1], int | float)
            and math.isfinite(item[1])
        ):
            kept.append((item[0], min(max(float(item[1]), 0.0), 100.0)))
    return kept


class ImageEntry(_Entry):
    id: Id | None = None  # library files
    filename: Text = ""
    name: Text | None = None
    author: Text | None = None
    subgroup: Text | None = None
    image_type: Annotated[Literal["battlemap", "scene"], _or_default("battlemap")] = "battlemap"
    media_type: Annotated[Literal["image", "video"], _or_default("image")] = "image"
    created_at: Annotated[datetime | None, OrNone] = None
    width: Annotated[Count | None, OrNone] = None
    height: Annotated[Count | None, OrNone] = None
    file_size: Annotated[Count | None, OrNone] = None
    grid: GridEntry = Field(default_factory=GridEntry)
    tags: list[TagEntry] = Field(default_factory=list, max_length=10_000)
    stored_hash: MaybeHash = None
    content_hash: MaybeHash = None
    pixel_hash: MaybeHash = None
    phash: Annotated[Int64 | None, OrNone] = None
    colors: Annotated[list[tuple[str, float]], BeforeValidator(_colors)] = Field(
        default_factory=list
    )
    vector: Annotated[str | None, Field(max_length=50_000), OrNone] = None
    path: Text | None = None  # groups files
    storage_key: Key | None = None  # library files, from here on
    thumbnail_key: Annotated[Key | None, OrNone] = None
    source_file_id: Id | None = None


class GroupEntry(_Entry):
    id: Id | None = None  # library files
    uid: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    base_name: Text = ""
    author: Text | None = None
    created_at: Annotated[datetime | None, OrNone] = None
    primary: Annotated[int | None, Field(ge=0), OrNone] = None  # an index into the line's images


class GroupLine(_Entry):
    group: GroupEntry | None = None
    images: list[ImageEntry] = Field(min_length=1, max_length=MAX_IMAGES_PER_LINE)

    @model_validator(mode="after")
    def _primary_in_range(self) -> GroupLine:
        if self.group and self.group.primary is not None and self.group.primary >= len(self.images):
            self.group.primary = None
        return self


class SourceFileEntry(_Entry):
    id: Id
    rel_key: Annotated[str, Field(min_length=1, max_length=4_096)]
    size: Count
    mtime_ns: Int64
    content_hash: MaybeHash = None
    state: Annotated[
        Literal["pending", "image", "duplicate", "skipped", "failed", "removed"],
        _or_default(FILE_PENDING),
    ]
    image_id: Id | None = None
    reason: Text | None = None
    missing_since: Annotated[datetime | None, OrNone] = None


class SourceFilesLine(_Entry):
    source_files: list[SourceFileEntry] = Field(min_length=1, max_length=_SOURCE_FILE_BATCH)


Line = Header | GroupLine | SourceFilesLine


# Vectors


def encode_vector(vector: Sequence[float] | np.ndarray) -> str:
    """Base64 of little-endian float32."""
    return base64.b64encode(np.asarray(vector, dtype="<f4").tobytes()).decode("ascii")


def decode_vector(text: str, dim: int) -> np.ndarray:
    """The embedding *text* encodes. Raises ``ValueError`` if it isn't *dim* finite floats."""
    raw = base64.b64decode(text, validate=True)
    if len(raw) != dim * 4:
        raise ValueError(f"vector has {len(raw) // 4} values, expected {dim}")
    vector = np.frombuffer(raw, dtype="<f4").copy()
    if not np.isfinite(vector).all():
        raise ValueError("vector has non-finite values")
    return vector


# Writing


def dump_line(line: BaseModel) -> str:
    """One validated line of the file, newline included. Nulls are left out. A line the
    reader would refuse as too long raises ``ExportError``."""
    text = json.dumps(
        line.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(text) >= MAX_LINE_CHARS:
        raise ExportError(f"A line of {len(text):,} characters is too long to export")
    return text + "\n"


def _validated[M: BaseModel](model: type[M], data: dict[str, Any], what: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ExportError(f"{what} can't be exported: {e.errors()[0]['msg']}") from e


def header_line(
    db: Session,
    *,
    kind: str,
    app_version: str,
    library_id: str | None,
    model: Mapping[str, Any] | None,
) -> Header:
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
    return _validated(Header, header, "The header")


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
    groups_query = select(ImageGroup).order_by(ImageGroup.id).limit(_GROUP_BATCH)
    if condition is not None:
        # Only the groups the selection touches, not every group in the library
        groups_query = groups_query.where(
            ImageGroup.id.in_(select(Image.group_id).where(condition, listed_images()))
        )
    after = 0
    while True:
        groups = db.scalars(groups_query.where(ImageGroup.id > after)).all()
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
    img: Image,
    *,
    kind: str,
    path: str | None = None,
    vector: Sequence[float] | np.ndarray | None = None,
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
        # The hash of the stored file: the bytes an export contains
        # (backfill_stored_hash fills it in for older rows).
        "stored_hash": img.stored_hash,
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
    """The ``group`` of a line holding *images*."""
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
) -> Iterator[GroupLine]:
    """The group lines (``iter_groups``), each validated: an image the reader would refuse
    fails here instead, naming it. *place* gives each image's path in ``groups`` files;
    *vectors* fills in embeddings."""
    for group, images in iter_groups(db, condition):
        found = vectors([img.id for img in images]) if vectors else {}
        paths = place(group, images) if place else [None] * len(images)
        for start in range(0, len(images), MAX_IMAGES_PER_LINE):
            chunk = images[start : start + MAX_IMAGES_PER_LINE]
            entries = [
                image_entry(img, kind=kind, path=path, vector=found.get(img.id))
                for img, path in zip(chunk, paths[start : start + MAX_IMAGES_PER_LINE], strict=True)
            ]
            line = {
                "group": group_entry(group, chunk, kind=kind) if group else None,
                "images": entries,
            }
            try:
                yield GroupLine.model_validate(line)
            except ValidationError as e:
                loc = e.errors()[0]["loc"]
                if loc[:1] == ("images",) and isinstance(loc[1], int):
                    what = f"Image {chunk[loc[1]].id}"
                else:
                    what = f"Group {group.id if group else None}"
                raise ExportError(f"{what} can't be exported: {e.errors()[0]['msg']}") from e


def source_file_lines(db: Session, exported: set[int]) -> Iterator[SourceFilesLine]:
    """Every ``source_files`` row, in batches. A row whose image isn't among *exported*
    (it was awaiting grouping) is written as ``pending`` with no image, so the scan after
    a rebuild queues the file again instead of skipping it for good."""
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
        entries = []
        for r in rows:
            state, image_id = r.state, r.image_id
            if state in (FILE_IMAGE, FILE_DUPLICATE) and image_id not in exported:
                state, image_id = FILE_PENDING, None
            entries.append(
                {
                    "id": r.id,
                    "rel_key": r.rel_key,
                    "size": r.size,
                    "mtime_ns": r.mtime_ns,
                    "content_hash": r.content_hash,
                    "state": state,
                    "image_id": image_id,
                    "reason": r.reason,
                    "missing_since": r.missing_since,
                }
            )
        yield _validated(SourceFilesLine, {"source_files": entries}, "A linked file")


def library_lines(
    db: Session,
    *,
    app_version: str,
    library_id: str | None,
    model: Mapping[str, Any] | None,
    vectors: VectorLookup | None,
    on_group: Callable[[GroupLine], None] | None = None,
) -> Iterator[str]:
    """Every line of a ``library`` file (a metadata export), as text. *on_group* sees each
    group line as it is written (progress, shutdown checks)."""
    yield dump_line(
        header_line(
            db, kind=KIND_LIBRARY, app_version=app_version, library_id=library_id, model=model
        )
    )
    exported: set[int] = set()
    for line in group_lines(db, kind=KIND_LIBRARY, vectors=vectors):
        exported.update(img.id for img in line.images if img.id is not None)
        if on_group:
            on_group(line)
        yield dump_line(line)
    for line in source_file_lines(db, exported):
        yield dump_line(line)


# Reading


def open_file(path: Path) -> io.TextIOWrapper:
    """*path* as text, gunzipped if it is gzip."""
    with path.open("rb") as probe:
        gzipped = probe.read(2) == b"\x1f\x8b"
    if gzipped:
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _lines(fp: io.TextIOBase | Iterable[str]) -> Iterator[tuple[int, str]]:
    """Numbered non-blank lines, each at most ``MAX_LINE_CHARS`` long."""
    if isinstance(fp, io.TextIOBase):
        # Read with a cap, so one huge "line" is refused before it is held in memory
        source: Iterable[str] = iter(lambda: fp.readline(MAX_LINE_CHARS + 1), "")
    else:
        source = fp
    for number, text in enumerate(source, start=1):
        if len(text) > MAX_LINE_CHARS:
            raise FormatError(number, "line is too long")
        if text.strip():
            yield number, text


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def _drop_bad_vectors(line: GroupLine, model: ModelInfo | None) -> None:
    """A vector that isn't the header model's size, or with no model, is dropped (the
    image is then re-embedded), so consumers can trust every vector they get."""
    for image in line.images:
        if image.vector is None:
            continue
        try:
            if model is None:
                raise ValueError("no model")
            decode_vector(image.vector, model.dim)
        except ValueError:
            image.vector = None


def read_lines(fp: io.TextIOBase | Iterable[str]) -> Iterator[Line]:
    """Every line of a file, validated: the ``Header`` first, then ``GroupLine`` and
    ``SourceFilesLine`` objects. Lines of a kind this version doesn't know are skipped.
    Raises ``FormatError`` at the first line it can't use."""
    header: Header | None = None
    for number, text in _lines(fp):
        try:
            obj = json.loads(text, parse_constant=_no_constants)
        except (ValueError, RecursionError) as e:
            raise FormatError(number, f"not valid JSON ({e})") from None
        if not isinstance(obj, dict):
            raise FormatError(number, "not a JSON object")
        try:
            if header is None:
                header = Header.model_validate(obj)
                if int(header.version.split(".")[0]) != MAJOR:
                    raise FormatError(number, f"version {header.version} is not supported")
                yield header
            elif "images" in obj:
                line = GroupLine.model_validate(obj)
                _drop_bad_vectors(line, header.model)
                yield line
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
