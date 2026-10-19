"""Library identity: markers, the rules for opening a library, the startup check and
inspecting folders (design/library-setup.md §1, §3)."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from backend.app import library_identity as li
from backend.app.library_identity import (
    APP_DATA_HOLDS_LINKED,
    APP_DATA_NOT_HERE,
    DIFFERENT_LIBRARY,
    MARKER_FILENAME,
    STARTUP_MESSAGES,
    STORE_HOLDS_LINKED,
    STORE_LACKS_MAPS,
    WIZARD_MESSAGES,
    DatabaseState,
    Found,
    LibraryMismatchError,
    Marker,
)
from backend.app.models import AppSetting, Image, get_engine, get_session_local, init_db
from backend.app.models.database import SETUP_COMPLETED_KEY
from backend.app.services.image_store import ImageStore
from backend.app.storage_lock import LOCK_FILENAME
from backend.pipeline.ingest_local import count_media, list_root

X = str(uuid.uuid4())
Y = str(uuid.uuid4())
KEY = "0123456789abcdef0123456789abcdef.jpg"


def marker(library_id: str = X, role: li.Role = "store") -> Marker:
    return Marker(library_id, role, {})


def database(library_id: str | None = X, *keys: str) -> DatabaseState:
    return DatabaseState(library_id=library_id, stored_keys=keys, setup_completed=False)


def decide(found: Found, *, linked: Path | None = None, root=Path("/lib")):
    return li.decide(app_data=root / "data", store=root / "images", linked=linked, found=found)


# The rules: every row of the startup check table (§3.3)


class TestDecide:
    def test_new_database_and_unmarked_store_is_a_new_library(self):
        assert decide(Found(None, None, False)) == li.Decision("new")

    def test_matching_ids_open(self):
        assert decide(Found(database(X), marker(X), False)) == li.Decision("open", library_id=X)

    def test_different_ids_are_refused(self):
        decision = decide(Found(database(X), marker(Y), False))
        assert (decision.outcome, decision.refusal) == ("error", DIFFERENT_LIBRARY)

    def test_new_database_with_a_marked_store_is_refused(self):
        decision = decide(Found(None, marker(X), False))
        assert (decision.outcome, decision.refusal) == ("error", APP_DATA_NOT_HERE)

    def test_unmarked_store_missing_the_databases_files_is_refused(self):
        decision = decide(Found(database(X, KEY), None, False))
        assert (decision.outcome, decision.refusal) == ("error", STORE_LACKS_MAPS)

    def test_unmarked_store_without_stored_files_is_marked(self):
        # e.g. a library that only uses a linked folder
        assert decide(Found(database(X), None, False)) == li.Decision("open", library_id=X)

    def test_older_library_is_adopted(self):
        # No ID yet: one is created on opening.
        assert decide(Found(database(None), None, False)) == li.Decision("open")

    def test_older_library_whose_store_holds_its_files_is_adopted(self):
        assert decide(Found(database(None, KEY), None, True)) == li.Decision("open")

    def test_older_library_with_a_marked_store_is_refused(self):
        decision = decide(Found(database(None), marker(X), False))
        assert (decision.outcome, decision.refusal) == ("error", DIFFERENT_LIBRARY)

    def test_store_that_lost_its_marker_but_holds_the_files_opens(self):
        decision = decide(Found(database(X, KEY), None, True))
        assert decision == li.Decision("open", library_id=X)

    def test_unknown_store_only_checks_the_database(self):
        decision = li.decide(
            app_data=Path("/lib/data"),
            store=None,
            linked=None,
            found=Found(database(X, KEY), None, False),
        )
        assert decision == li.Decision("open", library_id=X)


class TestContainment:
    """§1: the store and app data may sit inside the linked folder, never be or contain it."""

    @pytest.mark.parametrize(
        ("linked", "message"),
        [
            ("/lib/images", STORE_HOLDS_LINKED),
            ("/lib/images/Maps", STORE_HOLDS_LINKED),
            ("/lib/data", APP_DATA_HOLDS_LINKED),
            ("/lib/data/Maps", APP_DATA_HOLDS_LINKED),
        ],
    )
    def test_refused(self, linked, message):
        decision = decide(Found(database(X), marker(X), False), linked=Path(linked))
        assert (decision.outcome, decision.refusal) == ("error", message)

    @pytest.mark.parametrize("linked", ["/lib", "/", "/elsewhere/Maps", "/lib/images-old"])
    def test_allowed(self, linked):
        decision = decide(Found(database(X), marker(X), False), linked=Path(linked))
        assert decision.outcome == "open"

    def test_checked_before_a_new_library_is_made(self):
        decision = decide(Found(None, None, False), linked=Path("/lib/images"))
        assert decision.outcome == "error"


# Markers


class TestMarkers:
    def test_round_trip(self, tmp_path):
        written = Marker(X, "app_data", {"store": "/maps/Scene Atlas", "linked": None})
        li.write_marker(tmp_path, written)
        data = json.loads((tmp_path / MARKER_FILENAME).read_text(encoding="utf-8"))
        assert data == {
            "format": 1,
            "library_id": X,
            "role": "app_data",
            "hints": {"store": "/maps/Scene Atlas", "linked": None},
        }
        assert li.read_marker(tmp_path) == Marker(X, "app_data", {"store": "/maps/Scene Atlas"})
        assert [p.name for p in tmp_path.iterdir()] == [MARKER_FILENAME]

    def test_missing(self, tmp_path):
        assert li.read_marker(tmp_path) is None
        assert li.read_marker(tmp_path / "nowhere") is None

    @pytest.mark.parametrize(
        "content",
        [
            "{not json",
            "[]",
            "\xff\xfe",
            json.dumps({"format": 1, "role": "store"}),
            json.dumps({"format": 1, "library_id": "nope", "role": "store"}),
            json.dumps({"format": 1, "library_id": X, "role": "other"}),
            json.dumps({"format": 0, "library_id": X, "role": "store"}),
            json.dumps({"format": 1, "library_id": X, "role": "store", "hints": []}),
        ],
    )
    def test_corrupt_is_ignored(self, tmp_path, content):
        (tmp_path / MARKER_FILENAME).write_text(content, encoding="latin-1")
        assert li.read_marker(tmp_path) is None

    def test_store_inside_its_linked_folder_points_back_relatively(self, tmp_path):
        linked = tmp_path / "Battle Maps"
        store = linked / "Scene Atlas"
        app_data = tmp_path / "data"
        for folder in (store, app_data):
            folder.mkdir(parents=True)
        li.write_markers(X, app_data=app_data, store=store, linked=linked)

        store_marker = li.read_marker(store)
        assert store_marker == Marker(X, "store", {"app_data": str(app_data), "linked": ".."})
        assert li.read_marker(app_data) == Marker(
            X, "app_data", {"store": str(store), "linked": str(linked)}
        )
        assert li.marker_hints(store, store_marker) == {
            "app_data": str(app_data),
            "store": str(store),
            "linked": str(linked),
        }

    def test_one_folder_for_both_keeps_the_store_marker(self, tmp_path):
        li.write_markers(X, app_data=tmp_path, store=tmp_path, linked=None)
        assert li.read_marker(tmp_path) == Marker(X, "store", {"app_data": str(tmp_path)})


# Real folders: the startup check, opening, and reading a database


class Library:
    """A library's folders under ``root``, with a real (migrated) database."""

    def __init__(self, root: Path):
        self.app_data = root / "data"
        self.store = root / "images"
        self.linked: Path | None = None
        self.app_data.mkdir(parents=True)

    @property
    def db_path(self) -> Path:
        return self.app_data / li.DATABASE_FILENAME

    def session(self):
        engine = get_engine(f"sqlite:///{self.db_path}")
        init_db(engine)
        return get_session_local(engine)()

    def dirs(self) -> dict:
        return {"app_data": self.app_data, "store": self.store, "linked": self.linked}

    def check(self) -> li.Decision:
        return li.check_library(**self.dirs(), database=self.db_path)

    def open(self) -> str:
        self.check()
        with self.session() as db:
            return li.open_library(db, **self.dirs())

    def add_stored_image(self, key: str = KEY, *, file: bool = True) -> None:
        with self.session() as db:
            db.add(Image(filename="Map.jpg", storage_key=key))
            db.commit()
        if file:
            path = ImageStore(self.store).get_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")


@pytest.fixture
def lib(tmp_path) -> Library:
    return Library(tmp_path / "lib")


class TestStartup:
    def test_new_library_gets_an_id_a_store_and_both_markers(self, lib):
        library_id = lib.open()
        uuid.UUID(library_id)
        assert lib.store.is_dir()
        assert li.read_marker(lib.store) == Marker(
            library_id, "store", {"app_data": str(lib.app_data.resolve())}
        )
        assert li.read_marker(lib.app_data).library_id == library_id  # type: ignore[union-attr]

    def test_reopening_keeps_the_id(self, lib):
        library_id = lib.open()
        assert lib.check() == li.Decision("open", library_id=library_id)
        assert lib.open() == library_id

    def test_older_library_is_adopted(self, lib):
        lib.add_stored_image()  # a library from before IDs and markers
        assert li.read_database(lib.db_path) == DatabaseState(None, (KEY,), False)
        library_id = lib.open()
        assert li.read_marker(lib.store).library_id == library_id  # type: ignore[union-attr]

    def test_store_of_another_library_is_refused(self, lib, tmp_path):
        lib.open()
        li.write_marker(lib.store, marker(Y))
        with pytest.raises(
            LibraryMismatchError, match=re.escape(STARTUP_MESSAGES[DIFFERENT_LIBRARY])
        ):
            lib.check()

    def test_marked_store_without_its_database_is_refused(self, lib):
        lib.open()
        lib.db_path.unlink()
        with pytest.raises(
            LibraryMismatchError, match=re.escape(STARTUP_MESSAGES[APP_DATA_NOT_HERE])
        ):
            lib.check()

    def test_refusal_writes_nothing(self, lib):
        lib.store.mkdir()
        li.write_marker(lib.store, marker(Y))
        before = sorted(p.name for p in lib.app_data.iterdir())
        with pytest.raises(LibraryMismatchError):
            lib.check()
        assert sorted(p.name for p in lib.app_data.iterdir()) == before
        assert li.read_marker(lib.store) == marker(Y)

    def test_missing_store_with_stored_files_is_refused_not_created(self, lib):
        # e.g. an unmounted drive
        lib.add_stored_image(file=False)
        with pytest.raises(
            LibraryMismatchError, match=re.escape(STARTUP_MESSAGES[STORE_LACKS_MAPS])
        ):
            lib.check()
        assert not lib.store.exists()

    def test_empty_store_with_stored_files_is_refused(self, lib):
        lib.open()
        lib.add_stored_image(file=False)
        (lib.store / MARKER_FILENAME).unlink()
        with pytest.raises(
            LibraryMismatchError, match=re.escape(STARTUP_MESSAGES[STORE_LACKS_MAPS])
        ):
            lib.check()

    def test_lost_marker_is_rewritten_when_the_store_holds_the_files(self, lib):
        library_id = lib.open()
        lib.add_stored_image()
        (lib.store / MARKER_FILENAME).write_text("{corrupt", encoding="utf-8")
        assert lib.open() == library_id
        assert li.read_marker(lib.store).library_id == library_id  # type: ignore[union-attr]

    def test_new_store_for_a_library_without_stored_files(self, lib, tmp_path):
        library_id = lib.open()
        lib.store = tmp_path / "new-images"
        assert lib.open() == library_id
        assert li.read_marker(lib.store).library_id == library_id  # type: ignore[union-attr]

    def test_store_containing_the_linked_folder_is_refused(self, lib):
        lib.linked = lib.store / "Battle Maps"
        with pytest.raises(
            LibraryMismatchError, match=re.escape(STARTUP_MESSAGES[STORE_HOLDS_LINKED])
        ):
            lib.check()

    def test_linked_folder_need_not_exist(self, lib, tmp_path):
        lib.linked = tmp_path / "Unplugged"
        lib.open()
        assert li.read_marker(lib.store).hints["linked"] == str(lib.linked)  # type: ignore[union-attr]

    def test_database_state(self, lib):
        library_id = lib.open()
        with lib.session() as db:
            db.add(AppSetting(key=SETUP_COMPLETED_KEY, value_json=json.dumps("2026-10-19")))
            db.commit()
        lib.add_stored_image()
        assert li.read_database(lib.db_path) == DatabaseState(library_id, (KEY,), True)
        assert li.read_database(lib.app_data / "none.db") is None


# Inspecting folders the user picks


def inspect(**folders) -> li.Inspection:
    return li.inspect_folders(
        app_data=folders.get("app_data"),
        store=folders.get("store"),
        linked=folders.get("linked"),
        max_items=folders.get("max_items", 100),
    )


def maps_folder(root: Path, count: int) -> Path:
    for i in range(count):
        path = root / "Author" / "Pack" / f"Map {i}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    (root / "Author" / "notes.txt").write_text("not a map")
    (root / "Author" / "._Map 0.jpg").write_bytes(b"junk")
    return root


class TestInspect:
    def test_maps_folder_is_counted(self, tmp_path):
        result = inspect(linked=maps_folder(tmp_path / "Maps", 3))
        assert result.outcome == "new"
        assert result.linked == li.LinkedSummary("maps", 3, False)
        assert result.library is None

    def test_count_stops_at_the_limit(self, tmp_path):
        result = inspect(linked=maps_folder(tmp_path / "Maps", 5), max_items=4)
        assert result.linked == li.LinkedSummary("maps", 4, True)

    @pytest.mark.parametrize("make", [True, False])
    def test_empty_or_new_folder(self, tmp_path, make):
        linked = tmp_path / "Maps"
        if make:
            linked.mkdir()
        result = inspect(linked=linked)
        assert (result.outcome, result.linked) == ("new", li.LinkedSummary("empty", 0, False))

    def test_library_in_a_linked_folder_opens_with_its_hints(self, lib, tmp_path):
        lib.linked = maps_folder(tmp_path / "Battle Maps", 2)
        lib.store = lib.linked / li.STORE_SUBFOLDER
        library_id = lib.open()

        result = inspect(linked=lib.linked)
        assert result.outcome == "open"
        assert result.linked == li.LinkedSummary("library", 0, False)
        assert result.library == li.FoundLibrary(
            library_id,
            False,
            {
                "app_data": str(lib.app_data.resolve()),
                "store": str(lib.store.resolve()),
                "linked": str(lib.linked.resolve()),
            },
        )

    def test_library_whose_search_data_is_missing(self, lib, tmp_path):
        library_id = lib.open()
        lib.db_path.unlink()
        result = inspect(store=lib.store)
        assert (result.outcome, result.message) == ("error", WIZARD_MESSAGES[APP_DATA_NOT_HERE])
        assert result.library is not None
        assert (result.library.library_id, result.library.setup_completed) == (library_id, None)

    def test_folders_from_two_libraries(self, tmp_path):
        first, second = Library(tmp_path / "a"), Library(tmp_path / "b")
        first.open()
        second.open()
        result = inspect(app_data=first.app_data, store=second.store)
        assert (result.outcome, result.message) == ("error", WIZARD_MESSAGES[DIFFERENT_LIBRARY])

    def test_store_with_maps_for_a_new_library(self, tmp_path):
        result = inspect(store=maps_folder(tmp_path / "Maps", 1), app_data=tmp_path / "data")
        assert (result.outcome, result.message) == ("new", li.WIZARD_STORE_HAS_MAPS)
        assert result.store_has_maps is True

    def test_library_store_has_no_foreign_maps(self, lib):
        lib.open()
        lib.add_stored_image()
        assert inspect(store=lib.store).store_has_maps is False

    def test_store_holding_the_linked_folder(self, tmp_path):
        result = inspect(store=tmp_path, linked=maps_folder(tmp_path / "Maps", 1))
        assert (result.outcome, result.message) == ("error", WIZARD_MESSAGES[STORE_HOLDS_LINKED])

    def test_reads_nothing_it_changes(self, lib):
        lib.open()
        before = {p: p.stat().st_mtime_ns for p in lib.store.rglob("*")}
        inspect(app_data=lib.app_data, store=lib.store)
        assert {p: p.stat().st_mtime_ns for p in lib.store.rglob("*")} == before


# The walk skips library folders (§1)


@pytest.mark.parametrize("entry", [MARKER_FILENAME, LOCK_FILENAME])
def test_walk_skips_library_folders(tmp_path, entry):
    maps = maps_folder(tmp_path / "Maps", 2)
    library = maps_folder(maps / "Scene Atlas", 3)
    (library / entry).write_text("{}")
    assert count_media(maps, 100) == (2, False)
    assert all("Scene Atlas" not in f.relative_path for f in list_root(maps))
