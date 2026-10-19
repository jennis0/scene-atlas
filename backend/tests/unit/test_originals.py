"""The source interface for originals (design/library-setup.md §4.2): the linked folder's
walk and its containment check, and finding an image's original."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.library_identity import MARKER_FILENAME
from backend.app.models import Image, SourceFile
from backend.app.services import originals
from backend.app.services.image_store import ImageStore
from backend.app.services.originals import (
    LinkedFolder,
    OriginalUnavailable,
    linked_folder_available,
    original_path,
)


def write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def maps(tmp_path) -> Path:
    root = tmp_path / "Maps"
    write(root / "Czepeku" / "Forest" / "Forest_Day.png", b"day")
    return root


# ---------------------------------------------------------------------------
# list(): the scan's walk
# ---------------------------------------------------------------------------


def test_list_gives_keys_from_the_folder_itself(maps):
    """The parser reads the first part as the author, so the folder's own name is left out."""
    write(maps / "Czepeku" / "Forest" / "Forest_Night.webm", b"video")
    write(maps / "Czepeku" / "Forest" / "readme.txt")
    write(maps / "Czepeku" / "Forest" / "._Forest_Day.png")  # AppleDouble junk
    write(maps / "Pack.zip")  # archives aren't read in a linked folder
    found = {entry.rel_key: entry for entry in LinkedFolder(maps).list()}
    assert set(found) == {"Czepeku/Forest/Forest_Day.png", "Czepeku/Forest/Forest_Night.webm"}
    day = found["Czepeku/Forest/Forest_Day.png"]
    info = (maps / "Czepeku" / "Forest" / "Forest_Day.png").stat()
    assert (day.size, day.mtime_ns) == (3, info.st_mtime_ns)


def test_list_skips_the_librarys_own_folders(maps):
    """The desktop default keeps the store inside the linked folder."""
    store = maps / "Scene Atlas"
    write(store / MARKER_FILENAME, b"{}")
    write(store / "ab" / "cd" / "abcd.png")
    assert [e.rel_key for e in LinkedFolder(maps).list()] == ["Czepeku/Forest/Forest_Day.png"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_list_skips_symlinks(maps, tmp_path):
    outside = write(tmp_path / "outside" / "secret.png")
    (maps / "link.png").symlink_to(outside)
    (maps / "linked-dir").symlink_to(outside.parent, target_is_directory=True)
    assert [e.rel_key for e in LinkedFolder(maps).list()] == ["Czepeku/Forest/Forest_Day.png"]


# ---------------------------------------------------------------------------
# local_path(): the containment check
# ---------------------------------------------------------------------------


def test_local_path_reads_a_file_in_the_folder(maps):
    path = LinkedFolder(maps).local_path("Czepeku/Forest/Forest_Day.png")
    assert path.read_bytes() == b"day"


@pytest.mark.parametrize(
    "key",
    [
        "../outside.png",
        "Czepeku/../../outside.png",
        "",
        "Czepeku/Forest",  # a folder, not a file
        "Czepeku/Forest/nope.png",
        "bad\x00name.png",
    ],
)
def test_local_path_refuses_what_isnt_a_file_inside(maps, tmp_path, key):
    write(tmp_path / "outside.png", b"secret")
    with pytest.raises(OriginalUnavailable) as caught:
        LinkedFolder(maps).local_path(key)
    assert caught.value.state == "missing"


def test_local_path_refuses_an_absolute_key(maps, tmp_path):
    outside = write(tmp_path / "outside.png", b"secret")
    for key in (str(outside), outside.as_posix()):
        with pytest.raises(OriginalUnavailable):
            LinkedFolder(maps).local_path(key)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_local_path_refuses_symlinks(maps, tmp_path):
    outside = write(tmp_path / "outside" / "secret.png", b"secret")
    (maps / "link.png").symlink_to(outside)
    (maps / "inside-link.png").symlink_to(maps / "Czepeku" / "Forest" / "Forest_Day.png")
    (maps / "escape").symlink_to(outside.parent, target_is_directory=True)
    folder = LinkedFolder(maps)
    for key in ("link.png", "inside-link.png", "escape/secret.png"):
        with pytest.raises(OriginalUnavailable) as caught:
            folder.local_path(key)
        assert caught.value.state == "missing", key


def test_local_path_of_an_offline_folder(tmp_path):
    folder = LinkedFolder(tmp_path / "Unplugged")
    with pytest.raises(OriginalUnavailable) as caught:
        folder.local_path("Author/map.png")
    assert caught.value.state == "offline"
    assert caught.value.reason == "Unplugged isn't available"
    assert folder.stat("Author/map.png") is None


def test_the_folder_has_no_put_or_delete():
    """Read-only by type: nothing can write to the user's folder through it."""
    assert not hasattr(LinkedFolder, "put")
    assert not hasattr(LinkedFolder, "delete")


# ---------------------------------------------------------------------------
# original_path(): an image's original, stored or linked
# ---------------------------------------------------------------------------


@pytest.fixture
def linked_root(maps, monkeypatch):
    monkeypatch.setattr(settings, "linked_library_dir", maps)
    originals.forget_availability()
    yield maps
    originals.forget_availability()


def _linked_image(rel_key: str | None) -> Image:
    image = Image(filename="x.png", source_file_id=1)
    image.source_file = SourceFile(id=1, rel_key=rel_key, size=1, mtime_ns=1)
    return image


def test_original_of_a_stored_image(tmp_path, monkeypatch):
    store = ImageStore(tmp_path / "store")
    store.put_bytes("abcd.png", b"stored")
    monkeypatch.setattr("backend.app.services.get_image_store", lambda: store)
    assert original_path(Image(filename="x", storage_key="abcd.png")).read_bytes() == b"stored"
    with pytest.raises(OriginalUnavailable) as caught:
        original_path(Image(filename="x", storage_key="gone.png"))
    assert caught.value.state == "missing"


def test_original_of_a_linked_image(linked_root):
    assert original_path(_linked_image("Czepeku/Forest/Forest_Day.png")).read_bytes() == b"day"
    with pytest.raises(OriginalUnavailable) as caught:
        original_path(_linked_image("Czepeku/gone.png"))
    assert caught.value.state == "missing"
    # A row that gave up its path to an edited file (§4.5)
    with pytest.raises(OriginalUnavailable):
        original_path(_linked_image(None))


def test_original_of_a_linked_image_whose_folder_is_offline(linked_root, monkeypatch):
    os.rename(linked_root, linked_root.with_name("Elsewhere"))
    with pytest.raises(OriginalUnavailable) as caught:
        original_path(_linked_image("Czepeku/Forest/Forest_Day.png"))
    assert caught.value.state == "offline"
    # Detached: no folder configured
    monkeypatch.setattr(settings, "linked_library_dir", None)
    with pytest.raises(OriginalUnavailable) as caught:
        original_path(_linked_image("Czepeku/Forest/Forest_Day.png"))
    assert caught.value.state == "offline"


def test_file_state(linked_root):
    assert Image(filename="x", storage_key="k").file_state == "ok"
    image = _linked_image("Czepeku/Forest/Forest_Day.png")
    image.source_missing = False
    assert image.file_state == "ok"
    image.source_missing = True
    assert image.file_state == "missing"
    os.rename(linked_root, linked_root.with_name("Elsewhere"))
    originals.forget_availability()
    assert image.file_state == "offline"


def test_availability_is_remembered_briefly(linked_root):
    assert linked_folder_available()
    os.rename(linked_root, linked_root.with_name("Elsewhere"))
    assert linked_folder_available()  # remembered
    assert not linked_folder_available(fresh=True)
    assert not linked_folder_available()
