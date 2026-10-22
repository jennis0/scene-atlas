"""``partition_keys``: the effective top-level folder of each path (ingest refines large
imports partition by partition, design/ingestion.md §5.8)."""

from __future__ import annotations

from backend.app.services.variant_grouping import partition_keys


def test_a_creator_folder_is_a_partition():
    keys = partition_keys(["Czepeku/Keep/Keep Day.png", "Czepeku/Fort/Fort.png", "Tom/Cave.png"])
    assert keys == {
        "Czepeku/Keep/Keep Day.png": "czepeku",
        "Czepeku/Fort/Fort.png": "czepeku",
        "Tom/Cave.png": "tom",
    }


def test_rendition_and_variant_folders_at_the_root_are_transparent():
    keys = partition_keys(
        ["Gridded/Forest Road/a.png", "No Grid/Forest Road/b.png", "Night/Forest Road/c.png"]
    )
    assert set(keys.values()) == {"forest road"}


def test_mirror_siblings_share_a_partition():
    keys = partition_keys(["Forest Road Gridded/a.png", "Forest Road Gridless/b.png"])
    assert keys["Forest Road Gridded/a.png"] == keys["Forest Road Gridless/b.png"]


def test_files_at_the_root_form_the_empty_partition():
    assert partition_keys(["a.png", "Gridded/b.png"]) == {"a.png": "", "Gridded/b.png": ""}


def test_distinct_top_level_folders_stay_apart():
    keys = partition_keys(["Dungeon Room 1/a.png", "Dungeon Room 2/a.png"])
    assert keys["Dungeon Room 1/a.png"] != keys["Dungeon Room 2/a.png"]


def test_keys_do_not_depend_on_other_paths_or_order():
    paths = ["Czepeku/Keep/a.png", "Gridded/Forest/b.png", "c.png"]
    alone = partition_keys(paths)
    more = partition_keys([*reversed(paths), "Maps/Other/d.png", "Tom/e.png"])
    assert {p: more[p] for p in paths} == alone
    assert partition_keys([]) == {}
