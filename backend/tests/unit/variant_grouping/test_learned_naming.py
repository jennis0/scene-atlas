"""Tests of the learned namer (variant_grouping.learned_naming).

``learned_naming_fixtures.json`` holds 30 small imports with the names, authors and
``is_identity`` flags of the research namer given no known authors (scene-atlas-learning:
``python -m naming.extractive.export fixtures --no-gazetteer``). The port must match exactly.
"""

import json
from pathlib import Path

import pytest

from backend.app.services.variant_grouping import GroupingFile, learned_naming

from .support import run_paths

FIXTURES = json.loads(Path(__file__).with_name("learned_naming_fixtures.json").read_text())


@pytest.fixture
def rule_names():
    """The learned namer stays on (overrides the package's ``conftest``)."""


def files(paths: list[str]) -> list[GroupingFile[str]]:
    return [GroupingFile(p, p) for p in paths]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["description"])
def test_names_match_the_research_namer(fixture):
    g = run_paths(files(fixture["paths"]))
    got = {frozenset(grp.keys): (grp.name, grp.author, grp.name_is_identity) for grp in g.groups}
    want = {
        frozenset(x["paths"]): (x["name"], x["author"], x["is_identity"]) for x in fixture["groups"]
    }
    assert got == want


def test_known_authors_give_the_display_name():
    """Without known authors a folder author is the parser-cleaned folder name."""
    paths = [f"moonlight_maps/Hill Top/{g}/Hill Top Day.jpg" for g in ("Gridded", "Gridless")]
    assert run_paths(files(paths)).groups[0].author == "Moonlight"
    g = run_paths(files(paths), known_authors=["Moonlight Maps"])
    assert (g.groups[0].name, g.groups[0].author) == ("Hill Top", "Moonlight Maps")


def test_the_rules_name_groups_when_the_assets_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(learned_naming, "ASSET_DIR", tmp_path)
    learned_naming.load.cache_clear()
    try:
        assert learned_naming.load() is None
        paths = [
            f"limithron/Limithron Coral Reef 45x45/Limithron-Coral-Reef-{v}.jpg"
            for v in ("Day", "Night")
        ]
        group = run_paths(files(paths)).groups[0]
        assert (group.name, group.author) == ("Coral Reef", "limithron")
    finally:
        learned_naming.load.cache_clear()
