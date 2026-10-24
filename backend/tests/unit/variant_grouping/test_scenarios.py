"""Scenario tests from real library folders, plus the properties every run must have:
content only adds joins (paths-only groups refine content groups), determinism and input-order
independence."""

import random

import pytest

from backend.app.services.variant_grouping import (
    FolderReason,
    Grouping,
    GroupingFile,
    group_with_content,
)

from . import scenarios as S
from .support import CONTENT_PARAMS, by_prefix, group_of, parser, partition, run_content, run_paths


def paths_and_content(name: str) -> tuple[Grouping[str], Grouping[str]]:
    scenario = S.SCENARIOS[name]()
    return run_paths(scenario.grouping_files()), run_content(scenario)


class TestWizardTower:
    """Never Ending Wizard Tower: five rooms, one group."""

    def test_rooms_join_as_subgroups_with_content(self):
        _, g = paths_and_content("wizard_tower")
        tower = group_of(g, next(k for k in S.wizard_tower().files if "Wizard Tower" in k))
        assert tower.name == "Never Ending Wizard Tower"
        assert tower.author == "Moonlight Maps"
        assert len(tower.keys) == 30
        assert set(tower.subgroups.values()) == {
            "Beast Prison",
            "Cross Platform",
            "Garden",
            "Research Chamber",
            "Teleport Room",
        }
        assert "c1 parent+cohesion" in tower.reasons

    def test_each_room_is_one_group_by_paths(self):
        by_paths, _ = paths_and_content("wizard_tower")
        rooms = [g for g in by_paths.groups if "Never Ending Wizard Tower" in g.keys[0]]
        assert sorted(g.name for g in rooms) == [
            "Beast Prison",
            "Cross Platform",
            "Garden",
            "Research Chamber",
            "Teleport Room",
        ]
        assert all(len(g.keys) == 6 for g in rooms)

    def test_other_maps_of_the_maker_stay_apart(self):
        _, g = paths_and_content("wizard_tower")
        assert len(g.groups) == 11
        assert g.folders[("moonlight maps",)].container


class TestLeasealair:
    """leasealair: a house prefix on every file, numbered twins."""

    def test_house_prefix_does_not_lump_the_folder(self):
        by_paths, _ = paths_and_content("leasealair")
        named = [grp for grp in by_paths.groups if "leasealairMaps" in grp.keys[0]]
        assert len(named) == 12 and all(len(grp.keys) == 3 for grp in named)

    def test_numbered_twins_join_their_map_by_rendition(self):
        by_paths, g = paths_and_content("leasealair")
        numbered = [grp for grp in by_paths.groups if "NumberedGLMaps" in grp.keys[0]]
        assert len(numbered) == 12 and all(len(grp.keys) == 1 for grp in numbered)
        assert len(g.groups) == 12
        crystal = group_of(g, "leasealair/NumberedGLMaps_50.jpg")
        assert len(crystal.keys) == 4
        assert crystal.name == "Tom Cartos Crystal Caves"
        assert all("CrystalCaves" in k for k in crystal.keys if "leasealairMaps" in k)


class TestDndavid:
    """dndavid: one image per map, all in one style."""

    def test_one_group_per_map_however_cohesive(self):
        by_paths, g = paths_and_content("dndavid")
        assert len(by_paths.groups) == len(g.groups) == 22
        # a candidate location (no unit cap), whose catalog names keep every map apart
        assert g.folders[("dndavid",)].reason is FolderReason.LOCATION
        assert "a7 leaf default" not in g.decisions["dndavid"].joins
        assert {s.reason for s in g.suggestions} == {"cohesive, no folder/name evidence"}

    def test_names_come_from_the_files(self):
        _, g = paths_and_content("dndavid")
        names = {grp.name for grp in g.groups}
        assert {"Abandoned Temple", "Arbor Watch Tower", "Forest Ruins Temple"} <= names


class TestMoonlightPack:
    """Packs of different maps must not join."""

    def test_pack_maps_stay_apart(self):
        _, g = paths_and_content("moonlight_pack")
        pack = [grp for grp in g.groups if "Pack 02" in grp.keys[0]]
        assert sorted(grp.name for grp in pack) == sorted(S.PACK)
        assert g.folders[("moonlight maps", "pack 02")].reason is FolderReason.GENERIC

    def test_specific_parent_without_theme_does_not_join(self):
        _, g = paths_and_content("moonlight_pack")
        adventures = [grp for grp in g.groups if grp.keys[0].startswith("Forest Adventures/")]
        assert len(adventures) == 3


class TestTopicFolder:
    """Topic folders holding several makers."""

    def test_flat_topic_folder_keeps_every_map(self):
        _, g = paths_and_content("topic_folder")
        forests = [grp for grp in g.groups if grp.keys[0].startswith("Forests/")]
        assert len(forests) == len(S.MOONLIGHT_FOREST) + len(S.OTHER_FOREST)
        assert {"Forest Road", "Secluded Tea Valley", "Abandoned Campsite"} <= {
            grp.name for grp in forests
        }

    def test_recurring_author_folder_is_a_container(self):
        _, g = paths_and_content("topic_folder")
        assert g.folders[("woods", "moonlight maps")].reason is FolderReason.RECURRING
        woods = [grp for grp in g.groups if grp.keys[0].startswith("Woods/")]
        assert sorted(grp.name for grp in woods) == [
            "Druid Grove",
            "Forest Switch",
            "Forest Temple",
        ]


class TestCzepeku:
    def test_floors_are_subgroups_of_one_map(self):
        """japanese-castle-interior: five floors, level sub-groups."""
        _, g = paths_and_content("czepeku")
        castle = group_of(g, next(k for k in S.czepeku().files if "japanese" in k))
        assert castle.name == "Japanese Castle Interior"
        assert len(castle.keys) == 15
        assert set(castle.subgroups.values()) == {f"Floor {k}" for k in range(1, 6)}

    def test_variant_only_suffixes_group_by_name(self):
        by_paths, g = paths_and_content("czepeku")
        for grouping in (by_paths, g):
            flat = [grp for grp in grouping.groups if grp.keys[0].startswith("Czepeku Flat/")]
            assert sorted(grp.name for grp in flat) == [
                "Island Fort",
                "Orbital Lift",
                "Secluded Tea Valley",
                "Yggdrasil Roots",
            ]
            assert all(len(grp.keys) == 4 for grp in flat)


class TestMirrorFolders:
    def test_mirror_and_axis_split_folders_join_by_paths(self):
        by_paths, g = paths_and_content("mirror_folders")
        for grouping in (by_paths, g):
            assert sorted((grp.name, len(grp.keys)) for grp in grouping.groups) == [
                ("Forest Road", 4),
                ("Swamp Hut", 4),
            ]


# ----------------------------------------------------------------------------- properties


@pytest.mark.parametrize("name", sorted(S.SCENARIOS))
def test_content_only_merges_paths_only_groups(name):
    """Every content group is a union of paths-only groups: content only adds joins."""
    by_paths, content = paths_and_content(name)
    paths_of = {k: g for g, grp in enumerate(by_paths.groups) for k in grp.keys}
    for grp in content.groups:
        for k in grp.keys:
            members = by_paths.groups[paths_of[k]].keys
            assert set(members) <= set(grp.keys), (k, members)


@pytest.mark.parametrize("name", sorted(S.SCENARIOS))
def test_missing_features_still_only_merge(name):
    """With features for only some files, groups are still unions of the paths-only groups."""
    scenario = S.SCENARIOS[name]()
    content = scenario.content()
    for k in sorted(content)[::3]:
        del content[k]
    by_paths = partition(run_paths(scenario.grouping_files()))
    refined = partition(
        group_with_content(scenario.grouping_files(), content, CONTENT_PARAMS, parser())
    )
    assert all(any(s <= r for r in refined) for s in by_paths)


def _snapshot(g: Grouping[str]) -> tuple:
    groups = tuple(
        (tuple(grp.keys), grp.name, grp.author, tuple(sorted(grp.subgroups.items())),
         tuple(sorted(grp.reasons.items())))
        for grp in g.groups
    )  # fmt: skip
    suggestions = tuple((s.a, s.b, s.reason) for s in g.suggestions)
    folders = tuple(sorted(g.folders.items()))
    return groups, suggestions, folders, tuple(d.summary() for _, d in sorted(g.decisions.items()))


@pytest.mark.parametrize("name", sorted(S.SCENARIOS))
def test_output_is_independent_of_input_order(name):
    scenario = S.SCENARIOS[name]()
    files = scenario.grouping_files()
    content = scenario.content()
    expected_paths = _snapshot(run_paths(files))
    expected_content = _snapshot(group_with_content(files, content, CONTENT_PARAMS, parser()))
    rng = random.Random(name)
    for _ in range(3):
        shuffled = files[:]
        rng.shuffle(shuffled)
        reordered = dict(sorted(content.items(), key=lambda _: rng.random()))
        assert _snapshot(run_paths(shuffled)) == expected_paths
        got = group_with_content(shuffled, reordered, CONTENT_PARAMS, parser())
        assert _snapshot(got) == expected_content


def test_keys_need_not_be_paths():
    """Keys are the caller's (item ids); groups list them in path order."""
    scenario = S.mirror_folders()
    files = [GroupingFile(k, p) for k, p in enumerate(sorted(scenario.files, reverse=True))]
    g = run_paths(files)
    assert sorted(k for grp in g.groups for k in grp.keys) == list(range(len(files)))
    index = g.group_index()
    assert len(set(index.values())) == 2


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        run_paths([GroupingFile(1, "a/x.jpg"), GroupingFile(1, "a/y.jpg")])


def test_empty_input():
    assert run_paths([]).groups == []


def test_features_for_unknown_keys_are_ignored():
    scenario = S.mirror_folders()
    content = scenario.content() | {"not/a/file.jpg": next(iter(scenario.content().values()))}
    g = group_with_content(scenario.grouping_files(), content, CONTENT_PARAMS, parser())
    assert len(g.groups) == 2
    assert not by_prefix({k for grp in g.groups for k in grp.keys}, "not/")
