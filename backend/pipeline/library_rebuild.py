"""Rebuild the library's metadata from a ``library`` export (design/export-backup-move.md §8).

The flow: the file is staged (``staged_path``), ``check`` reads it once and says what would
change (images in it whose files are missing; images in the library it doesn't have),
``build`` writes a new database and vector table from it into ``rebuild/new/`` while the
app keeps running, and ``request_swap`` marks it to be swapped in at the next start
(``swap_if_pending``, early in the lifespan, before the library check). Nothing is merged,
and the live library is untouched until the swap: a failure before it changes nothing.

After the swap, ``set_aside`` moves the store files the rebuilt library doesn't use into
``not-in-backup/<timestamp>/`` in the readable layout, named from the old database, with a
``scene-atlas.jsonl`` that imports them again. The old database and vectors stay in
``rebuild/old-<id>/`` until the next rebuild, as the way back.

Derived data is not in the file and is made again after the swap by the usual startup
work: search text (``backfill_search_text``), vectors when the model differs
(``reconcile_vectors``), and the linked folder's state (its scan). Visual grouping
features are not rebuilt: grouping new imports into rebuilt groups goes by names.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import create_engine, delete, event, func, insert, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.colorspace import hex_to_lab
from backend.app.config import settings
from backend.app.library_identity import LIBRARY_ID_KEY
from backend.app.models.database import (
    FILE_DUPLICATE,
    FILE_IMAGE,
    FILE_PENDING,
    SETUP_COMPLETED_KEY,
    SOURCE_DETACHED,
    SOURCE_ONLINE,
    AppSetting,
    Color,
    Image,
    ImageGroup,
    LibrarySource,
    SourceFile,
    Tag,
    TagCategory,
    init_db,
)
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline import library_format as lf

logger = logging.getLogger(__name__)

JOB_NAME = "Rebuilding library"
SET_ASIDE_JOB = "Setting aside files not in the backup"
DB_NAME = "battlemap.db"  # in rebuild/new and old-<id>; the live one is live_db()
_SUFFIXES = ("", "-wal", "-shm")
# Kept from this install, whatever the file says
_OWN_SETTINGS = (
    LIBRARY_ID_KEY,
    "active_model",
    SETUP_COMPLETED_KEY,
    "moved_from",  # this install's old folders (library_move)
    # Sized to this machine's resources
    "max_concurrent_prepare",
    "max_concurrent_heavy_requests",
    "max_job_workers",
)
_BATCH = 1_000
LIST_GROUPS = 500  # groups listed in a check's report
LIST_IMAGES = 200  # images listed per group

ProgressFn = Callable[[int, int, str | None], None]


class RebuildError(ValueError):
    """The file can't be used to rebuild (shown to the user as is)."""


def live_db() -> Path:
    """The library's database file (``{data_dir}/battlemap.db``)."""
    return Path(make_url(settings.database_url).database or "")


def rebuild_dir() -> Path:
    """``{data_dir}/rebuild``: beside the database, on its volume, so moves are renames."""
    return live_db().parent / "rebuild"


def staged_path() -> Path:
    """The uploaded file (gzipped or not), in app data so it can't be unplugged."""
    return rebuild_dir() / "staged.jsonl"


def _check_path() -> Path:
    return rebuild_dir() / "check.json"


def _new_dir() -> Path:
    """The finished build; it is written as ``new.part`` and renamed when complete, so a
    build killed part way is never taken for a finished one."""
    return rebuild_dir() / "new"


def _part_dir() -> Path:
    return rebuild_dir() / "new.part"


def is_built() -> bool:
    return (_new_dir() / DB_NAME).is_file()


def _pending_path() -> Path:
    return rebuild_dir() / "pending.json"


def discard() -> None:
    """Forget a staged file, its check and an unswapped build (Cancel). A swap asked for
    but not yet done is forgotten too; one done isn't touched (its files are being set
    aside)."""
    staged_path().unlink(missing_ok=True)
    _check_path().unlink(missing_ok=True)
    _check_error_path().unlink(missing_ok=True)
    shutil.rmtree(_new_dir(), ignore_errors=True)
    shutil.rmtree(_part_dir(), ignore_errors=True)
    pending = _pending()
    if pending is not None and not pending.get("swapped"):
        _pending_path().unlink(missing_ok=True)


def busy() -> str | None:
    """Why no rebuild step can start now: a swap waiting for the restart, or files of the
    last one still being set aside."""
    pending = _pending()
    if pending is None:
        return None
    if pending.get("swapped"):
        return "The last rebuild is still setting its files aside; try again when it's done"
    return "A rebuild is waiting for Scene Atlas to restart"


# Check (§8.2)


@dataclass
class _Listed:
    """Images by group, for the report: counts, and the first names of the first groups."""

    images: int = 0
    groups: dict[str, list[str]] = field(default_factory=dict)
    group_count: int = 0

    def add(self, group: str, image: str) -> None:
        self.images += 1
        if group not in self.groups:
            self.group_count += 1
            if len(self.groups) >= LIST_GROUPS:
                return
            self.groups[group] = []
        names = self.groups[group]
        if len(names) < LIST_IMAGES:
            names.append(image)

    def report(self) -> dict:
        return {
            "images": self.images,
            "group_count": self.group_count,
            "groups": [{"name": g, "images": names} for g, names in self.groups.items()],
        }


def fingerprint(db: Session) -> list:
    """What changes when the library does: a check is only good for the library it saw."""
    # Counts and newest ids: an import, a delete, a tag added or removed, a group made or
    # merged. Not times: background work (hash and grid backfills) touches rows without
    # changing what a rebuild would lose. A rename slips through.
    images = db.execute(select(func.count(Image.id), func.max(Image.id))).one()
    groups = db.execute(select(func.count(ImageGroup.id), func.max(ImageGroup.id))).one()
    tags = db.execute(select(func.count(Tag.id), func.max(Tag.id))).one()
    return [*images, *groups, *tags]


@dataclass
class CheckResult:
    images: int
    groups: int
    created_at: str
    app_version: str
    different_library: bool
    reembed: bool  # the file's vectors aren't from the installed model
    linked_checked: bool  # the linked folder was online, so its files were checked
    missing: dict  # images in the file whose originals aren't there
    lost: dict  # images in the library that aren't in the file
    missing_stored: int  # of the missing, imported ones (left out of the build)
    # Linked images: kept whatever the check finds, the next scan marking missing files
    linked_missing: int = 0  # in the export, file not in the linked folder
    linked_lost: int = 0  # in the library, not in the export: imported again by a scan
    library: list = field(default_factory=list)  # fingerprint() when checked


def _first(lines) -> lf.Header:
    header = next(lines)  # read_lines yields the header first, or raises
    if not isinstance(header, lf.Header):
        raise RebuildError("The file has no header")
    return header


def _group_label(group: lf.GroupEntry | None) -> str:
    if group is None:
        return "Not in a group"
    return " – ".join(x for x in (group.author, group.base_name) if x) or "Unnamed group"


def _image_label(image: lf.ImageEntry) -> str:
    return image.name or image.filename or "(no name)"


def check(db: Session) -> CheckResult:
    """Read the staged file once, validating every line, and compare it with the library
    (*db*) and the files on disk. Changes nothing but the saved check. Raises
    ``RebuildError`` for a file that can't be used."""
    from backend.app.library_identity import get_library_id
    from backend.app.services import get_image_store
    from backend.app.services.originals import linked_folder_available
    from backend.pipeline.import_metadata import _installed_model

    path = staged_path()
    if not path.is_file():
        raise RebuildError("Upload an export first")
    store = get_image_store()
    missing, lost = _Listed(), _Listed()
    missing_stored = 0
    stored_keys: set[str] = set()
    linked_images: list[tuple[int, str, str]] = []  # (source file id, group, image)
    rel_keys: dict[int, str] = {}
    images = 0
    uids: set[str] = set()
    image_ids: set[int] = set()
    group_ids: dict[int, str] = {}
    try:
        with lf.open_file(path) as fp:
            lines = lf.read_lines(fp)
            header = _first(lines)
            if header.kind != lf.KIND_LIBRARY:
                raise RebuildError(
                    "That's a download or a library export (images and their metadata), "
                    "not a metadata backup. Import it instead."
                )
            for line in lines:
                raise_if_shutting_down()
                if isinstance(line, lf.SourceFilesLine):
                    rel_keys.update((f.id, f.rel_key) for f in line.source_files)
                    continue
                if not isinstance(line, lf.GroupLine):
                    continue
                if line.group is not None:
                    gid = line.group.id
                    if gid is None or group_ids.setdefault(gid, line.group.uid) != line.group.uid:
                        raise RebuildError("The file is damaged: a group id is missing or reused")
                    uids.add(line.group.uid)
                label = _group_label(line.group)
                for image in line.images:
                    if image.id is None or image.id in image_ids:
                        raise RebuildError("The file is damaged: an image id is missing or reused")
                    image_ids.add(image.id)
                    images += 1
                    if image.storage_key:
                        stored_keys.add(image.storage_key)
                        if not store.get_path(image.storage_key).is_file():
                            missing.add(label, _image_label(image))
                            missing_stored += 1
                    elif image.source_file_id is not None:
                        linked_images.append((image.source_file_id, label, _image_label(image)))
                    else:
                        missing.add(label, _image_label(image))
                        missing_stored += 1
    except lf.FormatError as e:
        raise RebuildError(f"The file can't be read: {e}") from None
    except (OSError, EOFError, UnicodeError) as e:
        raise RebuildError(f"The file can't be read: {e}") from None

    linked_dir = settings.linked_library_dir
    linked_checked = linked_dir is not None and linked_folder_available(fresh=True)
    linked_present: set[str] = set()
    linked_missing = 0
    for source_id, label, name in linked_images:
        rel = rel_keys.get(source_id)
        if rel is None:
            missing.add(label, name)  # no file listed for it: the build drops it
            missing_stored += 1
            continue
        linked_present.add(rel)
        if linked_checked and not _linked_file(linked_dir, rel):  # type: ignore[arg-type]
            linked_missing += 1

    # What the library has that the file doesn't
    rows = db.execute(
        select(Image.storage_key, SourceFile.rel_key, Image.name, Image.filename, ImageGroup)
        .outerjoin(SourceFile, SourceFile.id == Image.source_file_id)
        .outerjoin(ImageGroup, ImageGroup.id == Image.group_id)
        .order_by(Image.group_id, Image.id)
    )
    linked_lost = 0
    for key, rel, name, filename, group in rows:
        if (key and key in stored_keys) or (rel and rel in linked_present):
            continue
        if not key:
            linked_lost += 1  # its file stays in the linked folder; a scan imports it again
            continue
        label = (
            " – ".join(x for x in (group.author, group.base_name) if x)
            if group
            else "Not in a group"
        )
        lost.add(label, name or filename)

    encoder, _dim = _installed_model()
    result = CheckResult(
        images=images,
        groups=len(uids),
        created_at=header.created_at.isoformat(),
        app_version=header.app_version,
        different_library=header.library_id is not None and header.library_id != get_library_id(db),
        reembed=header.model is None or header.model.encoder_sha256 != encoder,
        linked_checked=linked_checked,
        missing=missing.report(),
        lost=lost.report(),
        missing_stored=missing_stored,
        linked_missing=linked_missing,
        linked_lost=linked_lost,
        library=fingerprint(db),
    )
    _check_error_path().unlink(missing_ok=True)
    _check_path().write_text(json.dumps(asdict(result)), encoding="utf-8")
    return result


def _linked_file(linked: Path, rel: str) -> bool:
    """*rel* (from the file: untrusted) names a file inside the linked folder."""
    path = (linked / rel).resolve()
    return path.is_relative_to(linked.resolve()) and path.is_file()


def _check_error_path() -> Path:
    return rebuild_dir() / "check-error.txt"


def check_error() -> str | None:
    """Why the staged file's last check failed, for Settings when reopened."""
    try:
        return _check_error_path().read_text(encoding="utf-8")
    except OSError:
        return None


def saved_check() -> CheckResult | None:
    """The check of the staged file, if it was checked."""
    try:
        return CheckResult(**json.loads(_check_path().read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


# Build (§8.3)


def _engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    return engine


def _own_settings(current: Session) -> dict[str, str | None]:
    """This install's own settings (kept whatever the export says), as stored."""
    return {
        s.key: s.value_json
        for s in current.scalars(select(AppSetting).where(AppSetting.key.in_(_OWN_SETTINGS)))
    }


def _settings_rows(header: lf.Header, own: dict[str, str | None]) -> list[dict]:
    rows = {
        key: json.dumps(value)
        for key, value in (header.settings or {}).items()
        if key not in _OWN_SETTINGS
    }
    rows |= own
    return [{"key": k, "value_json": v} for k, v in rows.items()]


def _category_rows(header: lf.Header) -> list[dict]:
    out, seen = [], set()
    for c in header.tag_categories:
        if c.name in seen:
            continue
        seen.add(c.name)
        values = [
            v.model_dump(exclude_none=True) if isinstance(v, lf.CommonValue) else v
            for v in c.common_values
        ]
        out.append(
            {
                "name": c.name,
                "description": c.description,
                "color": c.color,
                "icon": c.icon,
                "common_values": json.dumps(values) if values else None,
                "display_order": c.display_order,
            }
        )
    return out


def _image_row(image: lf.ImageEntry, group_id: int | None) -> dict:
    grid = image.grid
    return {
        "id": image.id,
        "filename": image.filename or f"image-{image.id}",
        "storage_key": image.storage_key,
        "source_file_id": image.source_file_id if not image.storage_key else None,
        "name": image.name,
        "author": image.author,
        "group_id": group_id,
        "width": image.width,
        "height": image.height,
        "file_size": image.file_size,
        "gridded": grid.gridded,
        "grid_width": grid.width,
        "grid_height": grid.height,
        "grid_type": grid.type,
        "grid_confidence": grid.confidence,
        "grid_source": grid.source,
        "subgroup": image.subgroup,
        "content_hash": image.content_hash,
        "stored_hash": image.stored_hash,
        "pixel_hash": image.pixel_hash,
        "phash": image.phash,
        "media_type": image.media_type,
        "image_type": image.image_type,
        "awaiting_grouping": False,
        "thumbnail_key": image.thumbnail_key,
        "created_at": image.created_at,
    }


class _Writer:
    """Rows waiting to be inserted, a batch at a time."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.rows: dict[type, list[dict]] = {}

    def add(self, model: type, row: dict) -> None:
        self.rows.setdefault(model, []).append(row)
        if len(self.rows[model]) >= _BATCH:
            self.flush()

    def flush(self) -> None:
        # Parents first: groups, then images, then what hangs off them
        for model in (LibrarySource, SourceFile, ImageGroup, Image, Tag, Color):
            rows = self.rows.pop(model, None)
            if rows:
                self.db.execute(insert(model), rows)
        self.db.commit()


def _vector_service(new: Path, header: lf.Header):
    """The new vector table, when the file's vectors are from the installed model."""
    from backend.app.services.lancedb_service import LanceDBService, get_lancedb_service
    from backend.pipeline.import_metadata import _installed_model

    encoder, dim = _installed_model()
    if header.model is None or encoder is None or header.model.encoder_sha256 != encoder:
        return None
    live = get_lancedb_service()  # the same table, in the new folder
    return LanceDBService(
        path=new / "lancedb", collection_name=live.collection_name, vector_size=dim
    )


def build(current: Session, progress_fn: ProgressFn | None = None) -> dict:
    """Write the rebuilt database (and vectors) into ``rebuild/new/`` from the checked file.
    Stops, leaving nothing, if more imported originals are missing than the check found
    (a folder has probably gone offline since)."""
    checked = saved_check()
    if checked is None:
        raise RebuildError("Check the file first")
    return _build(
        _own_settings(current),
        max_missing=checked.missing_stored,
        total=checked.images,
        vectors=True,
        progress_fn=progress_fn,
    )


def _build(
    own: dict[str, str | None],
    *,
    max_missing: int | None,
    total: int,
    vectors: bool,
    progress_fn: ProgressFn | None,
) -> dict:
    from backend.app.services import get_image_store

    shutil.rmtree(_new_dir(), ignore_errors=True)
    new = _part_dir()
    shutil.rmtree(new, ignore_errors=True)
    new.mkdir(parents=True, exist_ok=True)
    store = get_image_store()
    engine = _engine(new / DB_NAME)
    svc = None
    try:
        init_db(engine)
        db = sessionmaker(bind=engine)()
        with lf.open_file(staged_path()) as fp:
            lines = lf.read_lines(fp)
            header = _first(lines)
            # Upserts: a migration may have seeded rows of either
            for row in _settings_rows(header, own):
                db.execute(
                    sqlite_insert(AppSetting)
                    .values(row)
                    .on_conflict_do_update(index_elements=["key"], set_=row)
                )
            for row in _category_rows(header):
                db.execute(
                    sqlite_insert(TagCategory)
                    .values(row)
                    .on_conflict_do_update(index_elements=["name"], set_=row)
                )
            linked = settings.linked_library_dir
            source = LibrarySource(
                location=str(linked) if linked else "",
                state=SOURCE_ONLINE if linked else SOURCE_DETACHED,
            )
            db.add(source)
            db.commit()
            svc = _vector_service(new, header) if vectors else None
            loaded, left_out = _load(
                db, lines, source.id, store, svc, max_missing, total, progress_fn
            )
        # One file, no WAL: it moves into place as one
        db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        db.execute(text("PRAGMA journal_mode=DELETE"))
        db.close()
    except BaseException:
        if svc is not None:
            svc.close()
        engine.dispose()
        shutil.rmtree(new, ignore_errors=True)
        raise
    if svc is not None:
        svc.close()
    engine.dispose()
    os.replace(new, _new_dir())  # only now is it a finished build
    logger.info("Rebuild built: %d images, %d left out", loaded, left_out)
    return {"images": loaded, "left_out": left_out}


def build_in_place() -> str | None:
    """§8.5, at startup before the library check: the app data was lost (no database),
    and an export has been staged in its place (by the desktop app's "Rebuild from
    export…", or by hand on a server). Build it straight into place, unchecked: there's
    no library to lose. The store's library id is kept, so the store opens with it.
    Vectors aren't loaded (the installed model isn't known yet): images are embedded
    again after startup. Returns the rebuild id, if it built."""
    from backend.app.library_identity import read_marker

    live = live_db()
    if live.exists() or not staged_path().is_file():
        return None
    logger.warning("No database, and an export staged: rebuilding the library from it")
    with lf.open_file(staged_path()) as fp:
        header = _first(lf.read_lines(fp))
    marker = read_marker(settings.store_images_dir)
    library_id = marker.library_id if marker else header.library_id
    own: dict[str, str | None] = {}
    if library_id:
        own[LIBRARY_ID_KEY] = json.dumps(library_id)
    done = (header.settings or {}).get(SETUP_COMPLETED_KEY)
    if done is not None:  # the library was set up: the wizard isn't shown again
        own[SETUP_COMPLETED_KEY] = json.dumps(done)
    _build(own, max_missing=None, total=0, vectors=False, progress_fn=None)
    new = _new_dir()
    rebuild_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    # What's left of the lost library isn't this one's: a WAL would be replayed into the
    # new database, and vectors are keyed by its ids
    for suffix in ("-wal", "-shm"):
        live.with_name(live.name + suffix).unlink(missing_ok=True)
    if not _empty_dir(settings.vector_db_path):
        _move_folder(settings.vector_db_path, rebuild_dir() / f"old-{rebuild_id}" / "lancedb")
    _move(new / DB_NAME, live)
    shutil.rmtree(new, ignore_errors=True)
    # Swapped already: the set-aside runs after startup, as for any rebuild
    _pending_path().write_text(json.dumps({"id": rebuild_id, "swapped": True}), "utf-8")
    staged_path().unlink(missing_ok=True)
    _check_path().unlink(missing_ok=True)
    return rebuild_id


def _load(
    db, lines, source_id, store, svc, max_missing: int | None, total: int, progress_fn
) -> tuple[int, int]:
    writer = _Writer(db)
    groups: dict[str, int] = {}  # uid -> id
    counts: dict[int, int] = {}  # group id -> images kept
    primaries: dict[int, int] = {}
    kept: set[int] = set()
    vectors: list[dict] = []
    loaded = left_out = 0
    for line in lines:
        raise_if_shutting_down()
        if isinstance(line, lf.SourceFilesLine):
            for f in line.source_files:
                row = f.model_dump(exclude={"image_id"})
                row["source_id"] = source_id
                row["image_id"] = f.image_id if f.image_id in kept else None
                if row["image_id"] is None and row["state"] in (FILE_IMAGE, FILE_DUPLICATE):
                    row["state"] = FILE_PENDING  # as the export does: the next scan queues it
                writer.add(SourceFile, row)
            continue
        group_id = None
        if line.group is not None:
            group_id = groups.get(line.group.uid)
            if group_id is None:
                group_id = line.group.id  # checked: a library file's groups have ids
                groups[line.group.uid] = group_id  # type: ignore[assignment]
                writer.add(
                    ImageGroup,
                    {
                        "id": group_id,
                        "uid": line.group.uid,
                        "base_name": line.group.base_name or "Unnamed group",
                        "author": line.group.author,
                        "created_at": line.group.created_at,
                        "image_count": 0,
                    },
                )
        for index, image in enumerate(line.images):
            if not image.storage_key and image.source_file_id is None:
                left_out += 1
                continue
            if image.storage_key and not store.get_path(image.storage_key).is_file():
                left_out += 1
                if max_missing is not None and left_out > max_missing:
                    raise RebuildError(
                        "More images are missing than when the file was checked. Is a "
                        "folder offline? Check the file again."
                    )
                continue
            writer.add(Image, _image_row(image, group_id))
            kept.add(image.id)  # type: ignore[arg-type]
            for tag in image.tags:
                writer.add(
                    Tag,
                    {
                        "image_id": image.id,
                        "category": tag.category,
                        "value": tag.value,
                        "source": tag.source or "manual",
                        "confidence": 1.0 if tag.confidence is None else tag.confidence,
                    },
                )
            for order, (hex_color, pct) in enumerate(image.colors, start=1):
                lab = hex_to_lab(hex_color)
                writer.add(
                    Color,
                    {
                        "image_id": image.id,
                        "color_hex": hex_color,
                        "percentage": pct,
                        "color_order": order,
                        "lab_l": lab[0],
                        "lab_a": lab[1],
                        "lab_b": lab[2],
                    },
                )
            if group_id is not None:
                counts[group_id] = counts.get(group_id, 0) + 1
                if line.group and line.group.primary == index:
                    primaries[group_id] = image.id  # type: ignore[assignment]
            if svc is not None and image.vector:
                try:
                    vector = lf.decode_vector(image.vector, svc.vector_size)
                except ValueError:
                    vector = None
                if vector is not None:
                    vectors.append(
                        {
                            "image_id": image.id,
                            "embedding": vector.tolist(),
                            "metadata": {"filename": image.filename, "author": image.author or ""},
                        }
                    )
                    if len(vectors) >= _BATCH:
                        _add_vectors(svc, vectors)
            loaded += 1
            if progress_fn and loaded % 500 == 0:
                progress_fn(loaded, total, f"Rebuilt {loaded:,} of {total:,}")
    writer.flush()
    if svc is not None and vectors:
        _add_vectors(svc, vectors)
    # A linked image whose file the export didn't list has nothing to read: it goes
    dangling = select(Image.id).where(
        Image.storage_key.is_(None), Image.source_file_id.not_in(select(SourceFile.id))
    )
    gone = list(db.scalars(dangling))
    if gone:
        for model in (Tag, Color):
            db.execute(delete(model).where(model.image_id.in_(gone)))  # type: ignore[attr-defined]
        db.execute(delete(Image).where(Image.id.in_(gone)))
        for img_id in gone:
            kept.discard(img_id)
        loaded -= len(gone)
        left_out += len(gone)
        db.commit()
        db.expire_all()
        counts = {
            gid: n
            for gid, n in db.execute(
                select(Image.group_id, func.count(Image.id)).group_by(Image.group_id)
            )
            if gid is not None
        }
    # Group sizes and covers, now that their images are in (a cover left out falls back to
    # the group's first image); groups left empty go
    firsts = dict(
        db.execute(
            select(Image.group_id, func.min(Image.id))
            .where(Image.group_id.isnot(None))
            .group_by(Image.group_id)
        ).all()
    )
    for group_id in groups.values():
        group = db.get(ImageGroup, group_id)
        if group is None:
            continue
        if counts.get(group_id):
            group.image_count = counts[group_id]
            primary = primaries.get(group_id)
            group.primary_image_id = primary if primary in kept else firsts.get(group_id)
        else:
            db.delete(group)
    db.commit()
    return loaded, left_out


def _add_vectors(svc, vectors: list[dict]) -> None:
    if not svc.batch_add_embeddings(vectors):
        raise RebuildError("Writing the search data failed")
    vectors.clear()


# Swap (§8.3)


def request_swap() -> str:
    """Mark the build to be swapped in at the next start; returns the rebuild id."""
    if not is_built():
        raise RebuildError("There's no finished rebuild to apply")
    if _pending() is not None:
        raise RebuildError(busy() or "A rebuild is already waiting")
    rebuild_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    _pending_path().write_text(json.dumps({"id": rebuild_id, "swapped": False}), "utf-8")
    return rebuild_id


def _pending() -> dict | None:
    try:
        return json.loads(_pending_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def set_aside_pending() -> bool:
    """A swap has happened and its files are still to be set aside (the orphan sweep
    waits for it)."""
    pending = _pending()
    return bool(pending and pending.get("swapped"))


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)


def _empty_dir(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def _move_folder(src: Path, dest: Path) -> None:
    """Move the folder *src* to *dest*, unless done already. *dest* may be an empty folder
    (startup recreates the vector folder): it's replaced. Anything else there is an
    error, never overwritten."""
    if not src.exists():
        return
    if _empty_dir(dest):
        dest.rmdir()
    if dest.exists():
        if _empty_dir(src):
            src.rmdir()
            return
        raise RebuildError(f"Can't move {src} to {dest}: something is there already")
    _move(src, dest)


def swap_if_pending() -> str | None:
    """At startup, before the library check: put the built library in place, and the
    current one in ``rebuild/old-<id>/``. Each part is decided by what's where, so a crash
    part way is finished by the next start; nothing built is deleted until it's in place.
    Returns the rebuild id, if any."""
    pending = _pending()
    if pending is None or pending.get("swapped"):
        return None
    rebuild_id = pending["id"]
    new, old = _new_dir(), rebuild_dir() / f"old-{rebuild_id}"
    if not new.exists() and not old.exists():
        # Nothing was built for it (cancelled after Apply): forget it, change nothing
        _pending_path().unlink(missing_ok=True)
        return None
    for stale in rebuild_dir().glob("old-*"):
        if stale != old:  # the old library is only kept for the newest rebuild
            shutil.rmtree(stale, ignore_errors=True)
    live = live_db()
    old.mkdir(parents=True, exist_ok=True)
    if (new / DB_NAME).exists():  # the database isn't in place yet
        if live.exists():
            # The live database goes with its WAL, the main file last: while it's still
            # here, what's beside it is still its own
            for suffix in ("-wal", "-shm", ""):
                src = live.with_name(live.name + suffix)
                if src.exists():
                    _move(src, old / (DB_NAME + suffix))
        for suffix in ("-wal", "-shm"):  # any left now aren't the old one's: not kept
            live.with_name(live.name + suffix).unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", ""):  # the main file last: its arrival marks it done
            src = new / (DB_NAME + suffix)
            if src.exists():
                _move(src, live.with_name(live.name + suffix))
    # The live vectors go aside whether or not the build has its own: they're keyed by
    # the old library's image ids. Without built ones, images are embedded again.
    if not (old / "lancedb").exists() and not _empty_dir(settings.vector_db_path):
        _move_folder(settings.vector_db_path, old / "lancedb")
    if (new / "lancedb").exists():
        _move_folder(new / "lancedb", settings.vector_db_path)
    leftovers = list(new.iterdir()) if new.exists() else []
    if leftovers:
        raise RebuildError(f"The rebuilt library couldn't all be put in place: {leftovers}")
    shutil.rmtree(new, ignore_errors=True)
    staged_path().unlink(missing_ok=True)
    _check_path().unlink(missing_ok=True)
    pending["swapped"] = True
    _pending_path().write_text(json.dumps(pending), "utf-8")
    logger.info("Rebuild %s swapped in; the previous library is in %s", rebuild_id, old)
    return rebuild_id


# Set aside (§8.4)


def set_aside(progress_fn: ProgressFn | None = None) -> dict:
    """Move the store files the rebuilt library doesn't use into
    ``not-in-backup/<id>/``, named from the old database, with a ``scene-atlas.jsonl``
    written first, as the move log: a re-run carries on from it. Files the old database
    didn't know either go to ``unknown/``. Moves are renames: the folder is in the store."""
    from backend.app.services import get_image_store
    from backend.pipeline.db import pipeline_db
    from backend.pipeline.maintenance import store_files
    from backend.pipeline.naming import ReadableLayout

    pending = _pending()
    if not pending or not pending.get("swapped"):
        return {"moved": 0}
    rebuild_id = pending["id"]
    store = get_image_store()
    dest = settings.store_images_dir / "not-in-backup" / rebuild_id
    log = dest / lf.FILENAME
    with pipeline_db() as db:
        used = {k for (k,) in db.execute(select(Image.storage_key)) if k}
    files = {p.name: p for p in store_files(store.base_dir)}
    orphans = {k for k in files if k not in used}

    if not log.exists() and orphans:
        old_db = rebuild_dir() / f"old-{rebuild_id}" / DB_NAME
        dest.mkdir(parents=True, exist_ok=True)
        part = log.with_name(log.name + ".part")
        layout = ReadableLayout(root_len=len(str(dest.resolve())))
        known: set[str] = set()
        with part.open("w", encoding="utf-8") as out:
            out.write(
                lf.dump_line(
                    lf.Header(
                        format=lf.FORMAT,
                        version=lf.VERSION,
                        kind=lf.KIND_GROUPS,
                        app_version=settings.app_version,
                        created_at=datetime.now(UTC),
                    )
                )
            )
            if old_db.is_file():
                engine = _engine(old_db)
                try:
                    with sessionmaker(bind=engine)() as old:
                        order = lf.tag_category_order(old)
                        keys: dict[str, str] = {}

                        def keep(group, images):
                            return [i for i in images if i.storage_key in orphans]

                        def place(group, images):
                            paths = layout.place_images(group, images, order)
                            keys.update(zip(paths, [i.storage_key for i in images], strict=True))
                            return paths

                        for line in lf.group_lines(
                            old, kind=lf.KIND_GROUPS, keep=keep, place=place
                        ):
                            for entry in line.images:
                                entry.storage_key = keys.get(entry.path or "")
                                known.add(entry.storage_key or "")
                            out.write(lf.dump_line(line))
                finally:
                    engine.dispose()
            unknown = sorted(orphans - known)
            for start in range(0, len(unknown), lf.MAX_IMAGES_PER_LINE):
                line = lf.GroupLine(
                    images=[
                        lf.ImageEntry(filename=k, storage_key=k, path=f"unknown/{k}")
                        for k in unknown[start : start + lf.MAX_IMAGES_PER_LINE]
                    ]
                )
                out.write(lf.dump_line(line))
            out.flush()
            os.fsync(out.fileno())
        os.replace(part, log)

    moved = 0
    failed: list[str] = []
    if log.exists():
        with lf.open_file(log) as fp:
            entries = [
                (img.storage_key, img.path)
                for line in lf.read_lines(fp)
                if isinstance(line, lf.GroupLine)
                for img in line.images
                if img.storage_key and img.path
            ]
        for done, (key, rel) in enumerate(entries, start=1):
            raise_if_shutting_down()
            src = files.get(key)
            target = dest / PurePosixPath(rel)
            if src is not None and key not in used and not target.exists():
                try:
                    _move(src, target)
                except OSError as e:  # in use, say: left where it is, and said
                    failed.append(f"{key}: {e.strerror or e}")
                    logger.warning("Set aside: %s not moved: %s", key, e)
            if target.exists():
                moved += 1  # by this run or one before it
            if progress_fn and done % 200 == 0:
                progress_fn(done, len(entries), f"Set aside {done:,} of {len(entries):,} files")
    summary = {
        "id": rebuild_id,
        "moved": moved,
        "folder": str(dest) if moved else None,
        "not_moved": failed[:50],
    }
    (rebuild_dir() / "summary.json").write_text(json.dumps(summary), "utf-8")
    _pending_path().unlink(missing_ok=True)
    logger.info("Rebuild %s: %d file(s) set aside in %s", rebuild_id, moved, dest)
    return summary


def after_rebuild(progress_fn: ProgressFn | None = None) -> dict:
    """The job after a swap: set the unused files aside, then make the thumbnails the
    rebuilt rows name but this app data doesn't have."""
    from backend.pipeline.backfill_thumbnails import backfill_thumbnails

    summary = set_aside(progress_fn)
    summary["thumbnails"] = backfill_thumbnails(progress_fn)
    return summary


def set_aside_failed_export() -> None:
    """A staged export that couldn't be built at startup: kept, but not tried again."""
    staged = staged_path()
    if staged.exists():
        os.replace(staged, staged.with_name("staged-failed.jsonl"))
    shutil.rmtree(_part_dir(), ignore_errors=True)
    shutil.rmtree(_new_dir(), ignore_errors=True)


def dismiss_summary() -> None:
    (rebuild_dir() / "summary.json").unlink(missing_ok=True)


def last_summary() -> dict | None:
    try:
        return json.loads((rebuild_dir() / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# Jobs (api/rebuild.py submits them)


def check_job(progress_fn: ProgressFn | None = None) -> dict:
    from backend.pipeline.db import pipeline_db

    if progress_fn:
        progress_fn(0, 0, "Reading the export…")
    with pipeline_db() as db:
        try:
            return asdict(check(db))
        except Exception as e:
            _check_error_path().parent.mkdir(parents=True, exist_ok=True)
            _check_error_path().write_text(str(e), encoding="utf-8")
            raise


def build_job(progress_fn: ProgressFn | None = None) -> dict:
    from backend.pipeline.db import pipeline_db

    with pipeline_db() as db:
        return build(db, progress_fn)
