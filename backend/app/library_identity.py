"""Library identity: the library ID, its marker files, and the rules for opening a library.

A library is a database in the app data folder, a store for imported originals, and an
optional linked folder of the user's own maps (design/library-setup.md §1, §3). The
database's ``library_id`` is authoritative. A ``scene-atlas-library.json`` marker at the
root of the app data folder and of the store mirrors it, so a folder can be recognised
without opening SQLite, and records hints: where the library's other folders were last.

The rules live in one place, ``decide()``, a pure function over what was found in the
folders. The startup check (``check_library``) and ``POST /library/inspect``
(``inspect_folders``) gather what's in their folders and both call it.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from .config import settings
from .models.database import SETUP_COMPLETED_KEY, AppSetting

logger = logging.getLogger(__name__)

MARKER_FILENAME = "scene-atlas-library.json"
MARKER_FORMAT = 1
# app_settings key; not an AppSettings field, so the settings API can't change it.
LIBRARY_ID_KEY = "library_id"
DATABASE_FILENAME = "battlemap.db"
# Where the desktop app puts the store when a folder is linked: inside it.
STORE_SUBFOLDER = "Scene Atlas"
# How many of the database's stored files are looked for in a store without a marker.
_STORED_KEY_SAMPLE = 5

Role = Literal["app_data", "store"]
Outcome = Literal["new", "open", "error"]
LinkedKind = Literal["maps", "empty", "library"]

# Why folders can't be opened together. Each has two texts, both plain: the startup
# refusal (§3.3), which the desktop app shows as the loading page's headline, and the
# setup wizard's (§2.2), which names the folders as the wizard does.
Refusal = Literal[
    "different_library",
    "app_data_not_here",
    "store_lacks_maps",
    "store_holds_linked",
    "app_data_holds_linked",
]
DIFFERENT_LIBRARY: Refusal = "different_library"
APP_DATA_NOT_HERE: Refusal = "app_data_not_here"
STORE_LACKS_MAPS: Refusal = "store_lacks_maps"
STORE_HOLDS_LINKED: Refusal = "store_holds_linked"
APP_DATA_HOLDS_LINKED: Refusal = "app_data_holds_linked"

STARTUP_MESSAGES: dict[Refusal, str] = {
    DIFFERENT_LIBRARY: "The image folder belongs to a different library.",
    APP_DATA_NOT_HERE: (
        "This image folder belongs to a library whose search data folder isn't here."
    ),
    STORE_LACKS_MAPS: "The image folder doesn't contain this library's images.",
    STORE_HOLDS_LINKED: "The image folder can't be your images folder or contain it.",
    APP_DATA_HOLDS_LINKED: "The search data folder can't be your images folder or contain it.",
}
WIZARD_MESSAGES: dict[Refusal, str] = {
    DIFFERENT_LIBRARY: "These folders belong to different libraries.",
    APP_DATA_NOT_HERE: (
        "This library's search data folder is missing. Choose it, or pick another folder."
    ),
    STORE_LACKS_MAPS: "This Imported images folder doesn't have this library's images.",
    STORE_HOLDS_LINKED: "The Imported images folder can't be your images folder or a folder above it.",
    APP_DATA_HOLDS_LINKED: "The Search data folder can't be your images folder or a folder above it.",
}
WIZARD_DATABASE_UNREADABLE = "This search data folder's database can't be read."
WIZARD_STORE_HAS_MAPS = "This folder already has images in it."


class LibraryMismatchError(RuntimeError):
    """The configured folders can't be opened as one library, so the backend won't start."""


# Markers


@dataclass(frozen=True)
class Marker:
    library_id: str
    role: Role
    # The library's other folders, as written: absolute, or relative to the marker's folder.
    hints: dict[str, str | None]


def read_marker(folder: Path) -> Marker | None:
    """The marker in ``folder``, or None if there is none or it can't be understood."""
    path = folder / MARKER_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable library marker %s: %s", path, exc)
        return None
    try:
        if not isinstance(data, dict) or int(data["format"]) < 1:
            raise ValueError("not a library marker")
        if data["role"] not in ("app_data", "store"):
            raise ValueError(f"unknown role {data['role']!r}")
        hints = data.get("hints")
        if not isinstance(hints, dict | None):
            raise ValueError("hints aren't an object")
        hints = hints or {}
        return Marker(
            library_id=str(uuid.UUID(data["library_id"])),
            role=data["role"],
            hints={key: value for key, value in hints.items() if isinstance(value, str)},
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        logger.warning("Ignoring unreadable library marker %s: %s", path, exc)
        return None


def write_marker(folder: Path, marker: Marker) -> None:
    """Write ``marker`` into ``folder``, replacing any marker there in one step."""
    data = {
        "format": MARKER_FORMAT,
        "library_id": marker.library_id,
        "role": marker.role,
        "hints": marker.hints,
    }
    path = folder / MARKER_FILENAME
    temp = folder / f".{MARKER_FILENAME}.tmp"
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def write_markers(library_id: str, *, app_data: Path, store: Path, linked: Path | None) -> None:
    """Write both markers, with hints to the library's other folders."""
    app_data, store = app_data.resolve(), store.resolve()
    linked = linked.resolve() if linked is not None else None
    # A store inside its linked folder points at it relatively ("..") so the folder can
    # be found again on another machine, under another drive letter.
    linked_from_store = None
    if linked is not None:
        linked_from_store = (
            Path(os.path.relpath(linked, store)).as_posix()
            if _contains(linked, store)
            else str(linked)
        )
    # One folder for both keeps one marker: the store's, which the startup check reads.
    if not _same(app_data, store):
        write_marker(
            app_data,
            Marker(
                library_id,
                "app_data",
                {"store": str(store), "linked": str(linked) if linked else None},
            ),
        )
    write_marker(
        store, Marker(library_id, "store", {"app_data": str(app_data), "linked": linked_from_store})
    )


def rewrite_markers(db: Session) -> None:
    """Write the configured folders' markers again, e.g. after a library purge emptied
    the store. A store that isn't there (an unmounted drive) is left alone."""
    library_id = get_library_id(db)
    if library_id is None or not settings.store_images_dir.is_dir():
        return
    write_markers(
        library_id,
        app_data=settings.app_data_dir,
        store=settings.store_images_dir,
        linked=settings.linked_library_dir,
    )


def marker_hints(folder: Path, marker: Marker) -> dict[str, str | None]:
    """The marker's hints as absolute paths, with ``folder`` (where it was found) for its
    own role."""
    hints: dict[str, str | None] = {"app_data": None, "store": None, "linked": None}
    for role, hint in marker.hints.items():
        if role in hints and hint:
            hints[role] = str((folder / hint).resolve())
    hints[marker.role] = str(folder.resolve())
    return hints


# The library ID


def get_library_id(db: Session) -> str | None:
    row = db.query(AppSetting).filter(AppSetting.key == LIBRARY_ID_KEY).first()
    return json.loads(row.value_json) if row is not None and row.value_json else None


def _create_library_id(db: Session) -> str:
    library_id = str(uuid.uuid4())
    db.add(AppSetting(key=LIBRARY_ID_KEY, value_json=json.dumps(library_id)))
    db.commit()
    return library_id


# Reading a library's folders


@dataclass(frozen=True)
class DatabaseState:
    library_id: str | None  # None: a library from before library IDs
    stored_keys: tuple[str, ...]  # a few storage keys it references; empty if none
    setup_completed: bool


def read_database(path: Path) -> DatabaseState | None:
    """What the database at ``path`` says, read without changing it. None when there's no
    database yet (no file, or never set up). Raises ``sqlite3.Error`` if it can't be read."""
    if not path.is_file() or path.stat().st_size == 0:
        return None
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master")}
        if "images" not in tables:
            return None
        values: dict[str, str] = {}
        if "app_settings" in tables:
            rows = conn.execute(
                "SELECT key, value_json FROM app_settings WHERE key IN (?, ?)",
                (LIBRARY_ID_KEY, SETUP_COMPLETED_KEY),
            )
            values = {key: value for key, value in rows if value}
        keys = conn.execute(
            "SELECT storage_key FROM images WHERE storage_key IS NOT NULL ORDER BY id DESC LIMIT ?",
            (_STORED_KEY_SAMPLE,),
        )
        return DatabaseState(
            library_id=json.loads(values[LIBRARY_ID_KEY]) if LIBRARY_ID_KEY in values else None,
            stored_keys=tuple(key for (key,) in keys),
            setup_completed=SETUP_COMPLETED_KEY in values,
        )
    finally:
        conn.close()


def _store_in_linked(linked: Path) -> Path | None:
    """The store found in a linked folder: the folder itself, or its Scene Atlas
    subfolder, when it holds a store marker."""
    for folder in (linked, linked / STORE_SUBFOLDER):
        marker = read_marker(folder)
        if marker is not None and marker.role == "store":
            return folder
    return None


# The rules


@dataclass(frozen=True)
class Found:
    """What a library's folders hold, as far as the rules go."""

    database: DatabaseState | None  # None: no database (a new library)
    store_marker: Marker | None
    store_holds_files: bool  # some of the files the database references are in the store


def _found(
    database: DatabaseState | None, store: Path | None, store_marker: Marker | None
) -> Found:
    """What the rules need. The store is only searched for the database's files when it
    has no marker to go by."""
    from .services.image_store import ImageStore

    holds = False
    if database is not None and store is not None and store_marker is None:
        files = ImageStore(store)
        holds = any(files.get_path(key).is_file() for key in database.stored_keys)
    return Found(database, store_marker, holds)


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    refusal: Refusal | None = None  # why, for "error"
    library_id: str | None = None  # None: a new or older library, given an ID on opening


def _key(path: Path) -> Path:
    return Path(os.path.normcase(path))


def _contains(outer: Path, inner: Path) -> bool:
    """``inner`` is ``outer`` or inside it (both resolved)."""
    return _key(inner).is_relative_to(_key(outer))


def _same(a: Path, b: Path) -> bool:
    return _key(a) == _key(b)


def decide(
    *, app_data: Path | None, store: Path | None, linked: Path | None, found: Found
) -> Decision:
    """Whether the folders open as a new library, an existing one, or not at all.

    Paths are resolved; None means not known (inspect may not be sent all three). The
    store and app data may sit inside the linked folder but may not be or contain it:
    purge deletes the store's contents, which would include the user's maps.
    """
    if linked is not None:
        if store is not None and _contains(store, linked):
            return Decision("error", STORE_HOLDS_LINKED)
        if app_data is not None and _contains(app_data, linked):
            return Decision("error", APP_DATA_HOLDS_LINKED)

    database = found.database
    stored_id = found.store_marker.library_id if found.store_marker else None
    if database is None:
        if stored_id is not None:
            return Decision("error", APP_DATA_NOT_HERE)
        return Decision("new")
    if store is None:
        return Decision("open", library_id=database.library_id)
    if stored_id is not None:
        # A database from before library IDs never wrote a marker, so a marked store
        # belongs to another library.
        if stored_id != database.library_id:
            return Decision("error", DIFFERENT_LIBRARY)
        return Decision("open", library_id=stored_id)
    # No store marker. A store holding the database's files is this library's, from
    # before markers or with its marker lost: it's marked on opening. So is a new, empty
    # store (a library that only uses a linked folder). Otherwise it's the wrong folder,
    # or a drive that isn't mounted.
    if database.stored_keys and not found.store_holds_files:
        return Decision("error", STORE_LACKS_MAPS)
    return Decision("open", library_id=database.library_id)


# The startup check


def check_library(*, app_data: Path, store: Path, linked: Path | None, database: Path) -> Decision:
    """The startup check, before anything touches the folders: raises
    ``LibraryMismatchError`` if they can't be opened as one library.

    Read-only. ``open_library`` finishes the job once the database is ready.
    """
    decision = decide(
        app_data=app_data.resolve(),
        store=store.resolve(),
        linked=linked.resolve() if linked is not None else None,
        found=_found(read_database(database), store, read_marker(store)),
    )
    if decision.refusal is not None:
        raise LibraryMismatchError(STARTUP_MESSAGES[decision.refusal])
    return decision


def open_library(db: Session, *, app_data: Path, store: Path, linked: Path | None) -> str:
    """After ``check_library`` passed and the database is migrated: give a new or older
    library its ID, create an empty store if there's none, and write both markers.
    Returns the library ID."""
    library_id = get_library_id(db) or _create_library_id(db)
    # The check only passes a missing store when the database has no stored files.
    store.mkdir(parents=True, exist_ok=True)
    write_markers(library_id, app_data=app_data, store=store, linked=linked)
    return library_id


# Inspecting folders the user picks (desktop app)


@dataclass(frozen=True)
class LinkedSummary:
    kind: LinkedKind
    image_count: int
    capped: bool


@dataclass(frozen=True)
class FoundLibrary:
    library_id: str
    setup_completed: bool | None  # None when its app data wasn't found
    hints: dict[str, str | None]  # absolute


@dataclass(frozen=True)
class Inspection:
    outcome: Outcome
    message: str | None  # the wizard's text: a refusal, or the "already has maps" warning
    linked: LinkedSummary | None
    library: FoundLibrary | None
    store_has_maps: bool


def _inspect_linked(linked: Path, max_items: int) -> tuple[LinkedSummary, Path | None]:
    from backend.pipeline.ingest_local import count_media

    store = _store_in_linked(linked)
    if store is not None:
        return LinkedSummary("library", 0, False), store
    count, capped = count_media(linked, max_items) if linked.is_dir() else (0, False)
    return LinkedSummary("maps" if count else "empty", count, capped), None


def _has_maps(store: Path) -> bool:
    """Whether a folder chosen for a new store already holds images or videos."""
    from backend.pipeline.ingest_local import count_media

    return store.is_dir() and read_marker(store) is None and count_media(store, 1)[0] > 0


def inspect_folders(
    *, app_data: Path | None, store: Path | None, linked: Path | None, max_items: int
) -> Inspection:
    """What opening these folders would do (absolute paths; any may be left out). Folders
    not given are taken from the hints of a library found in the others. Read-only."""
    app_data, store, linked = (
        p.resolve() if p is not None else None for p in (app_data, store, linked)
    )

    linked_info, linked_store = (None, None)
    if linked is not None:
        linked_info, linked_store = _inspect_linked(linked, max_items)
    store_has_maps = store is not None and _has_maps(store)

    if store is None:
        store = linked_store
    store_marker = read_marker(store) if store is not None else None
    app_marker = read_marker(app_data) if app_data is not None else None

    hints: dict[str, str | None] = {}
    if store_marker is not None and store is not None:
        hints = marker_hints(store, store_marker)
    elif app_marker is not None and app_data is not None:
        hints = marker_hints(app_data, app_marker)
    if app_data is None and (hinted := hints.get("app_data")):
        app_data = Path(hinted)
        app_marker = read_marker(app_data)
    if store is None and (hinted := hints.get("store")):
        store = Path(hinted)
        store_marker = read_marker(store)
    if linked is None and (hinted := hints.get("linked")):
        linked = Path(hinted)

    try:
        state = read_database(app_data / DATABASE_FILENAME) if app_data is not None else None
    except sqlite3.Error as exc:
        logger.warning("Could not read the database in %s: %s", app_data, exc)
        return Inspection("error", WIZARD_DATABASE_UNREADABLE, linked_info, None, store_has_maps)

    decision = decide(
        app_data=app_data, store=store, linked=linked, found=_found(state, store, store_marker)
    )

    library = None
    library_id = (
        (store_marker.library_id if store_marker else None)
        or (state.library_id if state else None)
        or (app_marker.library_id if app_marker else None)
    )
    if library_id is not None:
        setup_completed = (
            state.setup_completed if state is not None and state.library_id == library_id else None
        )
        library = FoundLibrary(
            library_id,
            setup_completed,
            {
                "app_data": str(app_data) if app_data else None,
                "store": str(store) if store else None,
                "linked": str(linked) if linked else None,
            },
        )
    if decision.refusal is not None:
        message = WIZARD_MESSAGES[decision.refusal]
    else:
        message = WIZARD_STORE_HAS_MAPS if store_has_maps and decision.outcome == "new" else None
    return Inspection(decision.outcome, message, linked_info, library, store_has_maps)
