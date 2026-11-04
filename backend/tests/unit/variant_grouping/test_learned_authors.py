"""Authors from the learned namer on imports of whole libraries (design/variant-grouping-algorithm.md
§8, "Authors"): each maker's top-level folder is its author, under its own spelling, and one
maker's packs are not taken for makers.

Before the library rule, a bulk import of ``Creator/Map/files`` lost most unseen creators (the
author model scored them over the whole import, unlike its one-maker training imports) and
showed "Gloamwood Maps" as "Gloamwood".
"""

import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.services.image_parser import ImageParser
from backend.app.services.variant_grouping import GroupingFile, learned_naming
from backend.app.services.variant_grouping.learned_naming import namer
from backend.app.services.variant_grouping.learned_naming.text import Cleaner, shown_author
from stress_tests.ingest_scale_data import plan

from .support import run_paths

ONE_MAKER_PACKS = json.loads(Path(__file__).with_name("one_maker_packs.json").read_text())

LIBRARY = {
    "Brine and Bramble": ["Ancient Wharf", "Broken Chapel", "Sunken Shrine"],
    "Stoneguard Tiles": ["Crimson Bridge", "Burning Shrine", "Broken Bazaar"],
    "Gloamwood Maps": ["Emerald Watchtower", "Crimson Tavern", "Drowned Mill"],
    "Copperquill": ["Ancient Crypt", "Ancient Harbour", "Drowned Wharf"],
}


@pytest.fixture
def rule_names():
    """The learned namer stays on (overrides the package's ``conftest``)."""


def library(creators: dict[str, list[str]], root: str = "") -> list[str]:
    return [
        f"{root}{creator}/{name}/{name}_{variant}.jpg"
        for creator, maps in creators.items()
        for name in maps
        for variant in ("Day", "Night", "Winter")
    ]


def authors_by_top(paths: list[str], depth: int = 0) -> dict[str, set[str | None]]:
    """Per top-level folder (at ``depth``), the authors its groups got."""
    out: dict[str, set[str | None]] = defaultdict(set)
    for g in run_paths([GroupingFile(p, p) for p in paths]).groups:
        for key in g.keys:
            out[key.split("/")[depth]].add(g.author)
    return out


def test_each_creator_folder_of_a_library_is_its_groups_author():
    """Unseen names that read like map names ("and", "Tiles") still credit their folder."""
    assert authors_by_top(library(LIBRARY)) == {c: {c} for c in LIBRARY}


def test_a_maps_creator_keeps_maps():
    """The trailing "Maps" is dropped for matching only, never from the shown author."""
    got = authors_by_top(library(LIBRARY))
    assert got["Gloamwood Maps"] == {"Gloamwood Maps"}


def test_a_library_under_a_shared_container_folder():
    """A dropped ``Battle Maps`` folder holding the creators is not a level of its own."""
    got = authors_by_top(library(LIBRARY, "Battle Maps/"), depth=1)
    assert got == {c: {c} for c in LIBRARY}


def test_a_collection_folder_in_a_library_is_not_an_author():
    paths = library(LIBRARY) + [
        "community/Frozen Lake/Frozen Lake byUpsetti_Day.jpg",
        "community/Frozen Lake/Frozen Lake byUpsetti_Night.jpg",
        "community/old_maps/Old Keep_Day.jpg",
        "community/old_maps/Old Keep_Night.jpg",
    ]
    got = authors_by_top(paths)
    assert got["community"] == {"Upsetti", None}
    assert got["Copperquill"] == {"Copperquill"}


def test_the_ingest_benchmark_library_gets_its_creators():
    """The ingest benchmark's layout (stress_tests/ingest_scale.py): every group under a
    creator folder, one author per folder, and that author is the folder."""
    paths = [p.rel for p in plan(600, 1)]
    got = authors_by_top(paths)
    assert got == {c: {c} for c in got}
    assert len(got) == 12


def test_one_makers_packs_are_not_taken_for_makers(monkeypatch):
    """A maker's packs at the top (maker folder dropped) are not a library: scored over the
    whole import, no pack is credited as its groups' author, so packs keep the whole-import
    authors. Without that test the packs pass for makers."""
    paths = ONE_MAKER_PACKS["paths"]
    allowed = {None, "The MAD Cartographer"}

    def authors() -> set[str | None]:
        return {a for got in authors_by_top(paths).values() for a in got}

    assert authors() <= allowed
    monkeypatch.setattr(namer, "LIBRARY_TOPS", 0)  # every import a library
    assert not authors() <= allowed


@pytest.mark.parametrize(
    ("raw", "text", "shown"),
    [
        ("Gloamwood Maps", "Gloamwood", "Gloamwood Maps"),
        ("moonlight_maps", "Moonlight", "Moonlight Maps"),
        ("The Moonlight Maps", "The Moonlight", "The Moonlight Maps"),
        ("Beneos Battlemaps", "Beneos Battlemaps", "Beneos Battlemaps"),
        ("dice_grimorium", "Dice Grimorium", "Dice Grimorium"),
        ("Tom Cartos [Patreon]", "Tom Cartos", "Tom Cartos"),
    ],
)
def test_shown_author_puts_back_a_dropped_maps(raw, text, shown):
    assert shown_author(SimpleNamespace(raw=raw, text=text)) == shown


@pytest.mark.parametrize(
    ("picked", "name"),
    [
        ("Emerald Watchtower", "Emerald Watchtower"),
        ("Countryside Lane", "Countryside Lane"),
        ("Hidden Forrest", "Hidden Forrest"),
        ("Boatsontheshore Island Fort", "Boats on the Shore Island Fort"),
        ("Mountain King Tombof The Mountain Kings", "Mountain King Tomb of the Mountain Kings"),
        ("Dragoncryptlighting", "Dragon Crypt Lighting"),
    ],
)
def test_glued_words_split_in_two_only_around_of_or_the(picked, name):
    """Most two-part splits are real compounds or names ("Watch Tower", "For Rest")."""
    model = learned_naming.load()
    assert model is not None
    assert Cleaner(ImageParser(), model.tables)(picked) == name
