"""``effective_folders``: the folder a file belongs to once rendition and variant folders
are transparent (ingest finds a file's siblings by it at seal)."""

from __future__ import annotations

from backend.app.services.variant_grouping import effective_folders


def test_rendition_and_variant_folders_are_transparent():
    folders = effective_folders(
        ["Keep/Gridded/a.png", "Keep/No Grid/b.png", "Keep/Night/c.png", "Keep/d.png"]
    )
    assert len(set(folders.values())) == 1


def test_mirror_siblings_share_a_folder():
    folders = effective_folders(["Forest Road Gridded/a.png", "Forest Road Gridless/b.png"])
    assert folders["Forest Road Gridded/a.png"] == folders["Forest Road Gridless/b.png"]


def test_files_at_the_root_are_in_the_root():
    assert effective_folders(["a.png", "Gridded/b.png"]) == {"a.png": "", "Gridded/b.png": ""}


def test_distinct_folders_stay_apart():
    folders = effective_folders(["Czepeku/Keep/a.png", "Czepeku/Fort/a.png", "Tom/Keep/a.png"])
    assert len(set(folders.values())) == 3


def test_a_folder_does_not_depend_on_the_other_paths():
    paths = ["Czepeku/Keep/a.png", "Gridded/Forest/b.png", "c.png"]
    alone = effective_folders(paths)
    more = effective_folders([*reversed(paths), "Maps/Other/d.png", "Tom/e.png"])
    assert {p: more[p] for p in paths} == alone
    assert effective_folders([]) == {}
