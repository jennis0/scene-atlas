"""Tests of group names, authors and sub-group labels (variant_grouping.naming)."""

from backend.app.services.variant_grouping import GroupingFile
from backend.app.services.variant_grouping.names import tokenize_spans
from backend.app.services.variant_grouping.naming import _identity_span, _level_label

from .support import run_paths


def grouped(paths: list[str]):
    return run_paths([GroupingFile(p, p) for p in paths])


def only(paths: list[str]):
    g = grouped(paths)
    assert len(g.groups) == 1, [grp.name for grp in g.groups]
    return g.groups[0]


class TestFolderNames:
    """Rule 1: the folder the group occupies names it."""

    def test_folder_named_after_its_files(self):
        group = only(
            [f"Moonlight Maps/Forest Road/MA/Grid/Forest_Road_{v}.jpg" for v in ("Day", "Night")]
        )
        assert group.name == "Forest Road"

    def test_folder_name_is_cleaned_like_todays_groups(self):
        """Dimensions, tiers and the author prefix go, as in ``ImageParser._clean_group_name``."""
        group = only(
            [
                f"Dice Grimorium/Dilapidated Building Tier 2/Gridded/DilapidatedBuilding-{k}.jpg"
                for k in (1, 2, 3)
            ]
        )
        assert group.name == "Dilapidated Building"
        group = only(
            [
                f"limithron/Limithron Coral Reef 45x45/No Grid/Limithron-Coral-Reef-{v}-45x45.jpg"
                for v in ("Day", "Night", "Dawn")
            ]
        )
        assert (group.name, group.author) == ("Coral Reef", "limithron")

    def test_meaningful_folder_holding_exactly_the_group(self):
        """Heather House: files of mixed names, one folder."""
        group = only(
            [
                "Old Downloads/Heather House/MA/Grid/Moonlight_Maps_Heather_House_Basement_Lit_24x32_grid.jpg",
                "Old Downloads/Heather House/MA/Grid/Moonlight_Maps_Heather_House_Ground_Level_24x32_grid.jpg",
            ]
        )
        assert group.name == "Heather House"

    def test_mirror_folders_give_one_name(self):
        group = only([f"Maker/Forest Road {g}/ForestRoad_Day.jpg" for g in ("Gridded", "Gridless")])
        assert group.name == "Forest Road"


class TestIdentityNames:
    """Rule 2: the members' common identity, in a file name's own spelling."""

    def test_flat_folder_uses_the_file_names(self):
        g = grouped([f"2mtt/Docks of the Dead - {t} - 23x16.jpg" for t in ("Day", "Night")] +
                    [f"2mtt/Spell Scroll Store - {t} - 8x6.png" for t in ("Day", "Night")] +
                    [f"2mtt/Glowing Crater - {t}.jpg" for t in ("Day", "Night")])  # fmt: skip
        assert sorted(grp.name for grp in g.groups) == [
            "Docks of the Dead",
            "Glowing Crater",
            "Spell Scroll Store",
        ]

    def test_camel_case_and_slugs(self):
        g = grouped([f"Czepeku Flat/SecludedTeaValley_{v}.webp" for v in ("day", "fog", "rain")] +
                    [f"Czepeku Flat/yggdrasil-roots-{v}.webp" for v in ("day", "fog")] +
                    [f"Czepeku Flat/OrbitalLift_{v}.webp" for v in ("day", "night")])  # fmt: skip
        assert sorted(grp.name for grp in g.groups) == [
            "Orbital Lift",
            "Secluded Tea Valley",
            "Yggdrasil Roots",
        ]

    def test_identity_span(self):
        stem = "Moonlight_Maps_Docks_of_the_Dead_Night"
        start, end = _identity_span(tokenize_spans(stem), ("docks", "dead"))  # type: ignore[misc]
        assert stem[start:end] == "Docks_of_the_Dead"
        stem = "Dungeon_Vol_04_Night"
        start, end = _identity_span(tokenize_spans(stem), ("dungeon", "vol#4"))  # type: ignore[misc]
        assert stem[start:end] == "Dungeon_Vol_04"


class TestFallbackNames:
    def test_numbered_files_are_named_after_their_first_file(self):
        """Rule 3: no identity at all (``IMG_0001``): the first file's cleaned stem, so the
        groups stay distinguishable, flagged as not an identity name."""
        g = grouped([f"Camera/IMG_{k:04d}.jpg" for k in range(6)])
        assert len({grp.name for grp in g.groups}) == 6
        assert all(grp.name.startswith("IMG") for grp in g.groups)
        assert not any(grp.name_is_identity for grp in g.groups)

    def test_camera_counters_have_no_identity(self):
        """``IMG_001`` ... never join by name, whatever the family size."""
        g = grouped([f"Downloads/IMG_00{k}.png" for k in (1, 2, 3)])
        assert sorted(grp.name for grp in g.groups) == ["IMG 001", "IMG 002", "IMG 003"]
        assert not any(grp.name_is_identity for grp in g.groups)
        g = grouped([f"Phone/{s}.jpg" for s in ("DSC_0001", "PXL_20240101", "Screenshot 2")])
        assert len(g.groups) == 3

    def test_one_word_names_with_numbers_still_join(self):
        group = only(["Maps/Cave_01.png", "Maps/Cave_02.png"])
        assert (group.name, group.name_is_identity) == ("Cave", True)

    def test_identity_names_are_flagged(self):
        assert only(["M/Forest Road/ForestRoad_Day.jpg"]).name_is_identity
        assert only(["2mtt/Docks of the Dead - Day.jpg"]).name_is_identity


class TestAuthors:
    def test_author_is_the_creator_folder(self):
        assert only(["czepeku/Island Fort/IslandFort_Night.jpg"]).author == "czepeku"

    def test_top_folder_naming_the_group_is_not_its_author(self):
        """``Golden Forest/GoldenForest_Night.jpg``: the folder is the map (``folder_is_group``)."""
        group = only([f"Golden Forest/GoldenForest_{v}.jpg" for v in ("Night", "Day", "Snow")])
        assert (group.name, group.author) == ("Golden Forest", None)

    def test_rendition_folders_are_not_authors(self):
        group = only([f"{g}/Swamp Hut/SwampHut_Day.jpg" for g in ("Gridded", "Gridless")])
        assert (group.name, group.author) == ("Swamp Hut", None)

    def test_by_author_in_the_file_name(self):
        group = only([f"Arena_byUpsetti_{v}.jpg" for v in ("Day", "Night")])
        assert (group.name, group.author) == ("Arena", "Upsetti")

    def test_known_author_folder_wins(self):
        """A folder named after a creator already in the library is the author, wherever it
        sits (``compute_plan`` passes the gallery's authors)."""
        paths = [
            f"Forests/moonlight maps/Forest Road/Forest_Road_{v}.jpg" for v in ("Day", "Night")
        ]
        g = run_paths([GroupingFile(p, p) for p in paths], known_authors=["Moonlight Maps"])
        assert (g.groups[0].name, g.groups[0].author) == ("Forest Road", "Moonlight Maps")

    def test_known_author_folder_never_names_a_map(self):
        paths = [f"Upsetti/Arena_{v}.jpg" for v in ("Day", "Night")]
        g = run_paths([GroupingFile(p, p) for p in paths], known_authors=["Upsetti"])
        assert (g.groups[0].name, g.groups[0].author) == ("Arena", "Upsetti")

    def test_house_prefix_folder_is_the_author(self):
        """The stripped prefix ``moonlight maps`` names the maker folder below the topic."""
        paths = [
            f"Woods/Moonlight Maps/{m}/MA/Moonlight_Maps_{m.replace(' ', '_')}_{v}.jpg"
            for m in ("Forest Cottage", "Forest Switch")
            for v in ("Grass01", "Snow02_Night")
        ]
        assert {grp.author for grp in grouped(paths).groups} == {"Moonlight Maps"}

    def test_folder_naming_the_group_is_never_its_author(self):
        """``A/Keep/Keep Day.png`` -> author "A" (one-letter folders count), and
        ``Keep/Keep Day.png`` -> no author; never "Keep"."""
        group = only(["A/Keep/Keep Day.png", "A/Keep/Keep Night.png"])
        assert (group.name, group.author) == ("Keep", "A")
        group = only(["Keep/Keep Day.png", "Keep/Keep Night.png"])
        assert (group.name, group.author) == ("Keep", None)

    def test_folder_containing_the_group_through_rendition_folders_is_its_author(self):
        """``Maker/Gridded/…`` and ``Maker/Gridless/…``: Maker only contains the group."""
        paths = ["Maker/Gridded/Lantern Pass Day.png", "Maker/Gridless/Lantern Pass Day.png"]
        group = only([*paths, "Maker/Gridded/Lantern Pass Night.png"])
        assert (group.name, group.author) == ("Lantern Pass", "Maker")

    def test_files_at_the_root_have_no_folder_author(self):
        assert only([f"Arena_{v}.jpg" for v in ("Day", "Night")]).author is None


class TestSubgroupLabels:
    def test_level_labels(self):
        assert _level_label("floor#2") == "Floor 2"
        assert _level_label("roof") == "Roof"

    def test_levels_label_files_and_main_files_have_none(self):
        group = only(
            ["2mtt/Grand Inn - Floor 1.png", "2mtt/Grand Inn - Floor 2.png", "2mtt/Grand Inn.png"]
        )
        assert group.subgroups == {
            "2mtt/Grand Inn - Floor 1.png": "Floor 1",
            "2mtt/Grand Inn - Floor 2.png": "Floor 2",
        }

    def test_trailing_level_words_are_not_the_name(self):
        group = only(["2mtt/Grand Inn - Floor 1.png", "2mtt/Grand Inn - Floor 2.png"])
        assert group.name == "Grand Inn"

    def test_single_level_is_no_subgroup(self):
        group = only(["2mtt/Grand Inn - Roof.png", "2mtt/Grand Inn - Roof Night.png"])
        assert group.subgroups == {}
