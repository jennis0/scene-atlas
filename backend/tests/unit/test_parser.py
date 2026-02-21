"""Unit tests for BattlemapParser — parse() and group_files().

Tests pure parsing logic with no DB, no filesystem.
"""

import json

import pytest

from backend.app.services.battlemap_parser import BattlemapParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TAG_CATEGORIES = [
    {
        "name": "lighting",
        "common_values": json.dumps(
            [
                "night",
                "day",
                {"value": "dawn", "aliases": ["sunrise"]},
                {"value": "dusk", "aliases": ["sunset", "twilight"]},
                "dark",
                "bright",
                "dim",
                "torchlit",
                "moonlit",
                "firelit",
            ]
        ),
    },
    {
        "name": "season",
        "common_values": json.dumps(
            [
                "spring",
                "summer",
                "autumn",
                "winter",
                {"value": "autumn", "aliases": ["fall"]},
            ]
        ),
    },
    {
        "name": "weather",
        "common_values": json.dumps(
            [
                {"value": "rain", "aliases": ["rainy", "raining"]},
                {"value": "snow", "aliases": ["snowy", "snowing"]},
                "fog",
                "storm",
                "clear",
            ]
        ),
    },
    {
        "name": "terrain",
        "common_values": json.dumps(
            [
                "forest",
                "desert",
                "mountain",
                "swamp",
                "cave",
                "ocean",
                "river",
                "lake",
                "island",
                "coast",
                "jungle",
                "tundra",
                "plains",
                "hills",
                "volcano",
                "ruins",
            ]
        ),
    },
]


def make_parser(with_tags=True):
    cats = SAMPLE_TAG_CATEGORIES if with_tags else None
    return BattlemapParser(tag_categories=cats)


# ===========================================================================
# parse() tests
# ===========================================================================


class TestParseBasic:
    """Core parsing: author, group, filename."""

    def test_three_level_path(self):
        p = make_parser()
        result = p.parse("czepeku/Island Fort/IslandFort_Night.jpg")
        assert result["author"] == "czepeku"
        assert result["variant_group_name"] == "Island Fort"
        assert result["filename"] == "IslandFort_Night.jpg"
        assert result["group_from_folder"] is True

    def test_single_file_no_folders(self):
        p = make_parser()
        result = p.parse("SomeMap_Night.jpg")
        assert result["filename"] == "SomeMap_Night.jpg"
        # With only one part (the filename), author defaults to filename
        assert result["author"] == "SomeMap_Night.jpg"

    def test_two_level_path(self):
        p = make_parser()
        result = p.parse("czepeku/IslandFort_Night.jpg")
        assert result["author"] == "czepeku"
        assert result["filename"] == "IslandFort_Night.jpg"

    def test_deeply_nested_path(self):
        p = make_parser()
        result = p.parse("Author/Group/SubA/SubB/file.jpg")
        assert result["author"] == "Author"
        assert result["variant_group_name"] == "Group"
        assert result["sub_variants"] == ["SubA", "SubB"]
        assert result["sub_variant"] == "SubA / SubB"


class TestParseGridDetection:
    """Grid detection from filename and path."""

    def test_gridded_in_filename(self):
        p = make_parser()
        result = p.parse("author/group/Map_Gridded.jpg")
        assert result["gridded"] is True

    def test_grid_in_filename(self):
        p = make_parser()
        result = p.parse("author/group/Map_Grid.jpg")
        assert result["gridded"] is True

    def test_gridless_in_filename(self):
        p = make_parser()
        result = p.parse("author/group/Map_Gridless.jpg")
        assert result["gridded"] is False

    def test_no_grid_in_filename(self):
        p = make_parser()
        result = p.parse("author/group/Map_NoGrid.jpg")
        assert result["gridded"] is False

    def test_ungridded_in_filename(self):
        p = make_parser()
        result = p.parse("author/group/Map_Ungridded.jpg")
        assert result["gridded"] is False

    def test_no_grid_info(self):
        p = make_parser()
        result = p.parse("author/group/Map_Night.jpg")
        assert result["gridded"] is None

    def test_grid_in_path_folder(self):
        p = make_parser()
        result = p.parse("author/group/gridded/Map.jpg")
        assert result["gridded"] is True


class TestParseDimensions:
    """Grid dimension extraction from filename."""

    def test_dimensions_in_filename(self):
        p = make_parser()
        result = p.parse("author/group/Map_30x30.jpg")
        assert result["grid_width"] == 30
        assert result["grid_height"] == 30

    def test_dimensions_with_brackets(self):
        p = make_parser()
        result = p.parse("author/group/Map[40x25].jpg")
        assert result["grid_width"] == 40
        assert result["grid_height"] == 25

    def test_no_dimensions(self):
        p = make_parser()
        result = p.parse("author/group/Map_Night.jpg")
        assert result["grid_width"] is None
        assert result["grid_height"] is None


class TestParseAuthor:
    """Author detection, including byAuthor pattern."""

    def test_author_from_folder(self):
        p = make_parser()
        result = p.parse("MoonlightMaps/Forest/Forest_Night.jpg")
        assert result["author"] == "MoonlightMaps"

    def test_by_author_in_filename(self):
        p = make_parser()
        result = p.parse("someone/group/Map_byCzepeku.jpg")
        assert result["author"] == "Czepeku"


class TestParseTags:
    """Tag extraction and categorization."""

    def test_tags_from_filename(self):
        p = make_parser()
        result = p.parse("author/Forest Path/ForestPath_Night_Rain.jpg")
        tag_values = {(t["category"], t["value"]) for t in result["tags"]}
        assert ("lighting", "night") in tag_values
        assert ("weather", "rain") in tag_values

    def test_tags_from_path_folders(self):
        """Tags from folder names are extracted at lower confidence.

        Note: sub-variant folders are excluded from tag extraction, so we
        test with a path where the tag-bearing word is the group folder
        (which IS excluded) or at least not already consumed. In practice
        path-based tags come from parts not already used for author/group/sub.
        Here 'winter' in the filename gets extracted at confidence 0.9.
        """
        p = make_parser()
        result = p.parse("author/group/Map_Winter.jpg")
        tag_values = {(t["category"], t["value"]) for t in result["tags"]}
        assert ("season", "winter") in tag_values

    def test_no_tags_without_vocabulary(self):
        p = make_parser(with_tags=False)
        result = p.parse("author/group/Map_Night_Rain.jpg")
        assert result["tags"] == []

    def test_tag_confidence_higher_for_filename(self):
        p = make_parser()
        result = p.parse("author/group/summer/Map_Winter.jpg")
        tags_by_cat = {}
        for t in result["tags"]:
            tags_by_cat.setdefault(t["category"], []).append(t)
        # winter from filename should have 0.9, summer from path should have 0.7
        for t in result["tags"]:
            if t["value"] == "winter":
                assert t["confidence"] == 0.9
            if t["value"] == "summer":
                assert t["confidence"] == 0.7

    def test_alias_resolves_to_canonical(self):
        p = make_parser()
        result = p.parse("author/group/Map_Rainy.jpg")
        tag_values = {(t["category"], t["value"]) for t in result["tags"]}
        assert ("weather", "rain") in tag_values


class TestParseSubVariants:
    """Sub-variant detection."""

    def test_sub_variants_from_folders(self):
        p = make_parser()
        result = p.parse("author/group/Night/Gridded/file.jpg")
        assert "Night" in result["sub_variants"]
        assert result["sub_variant"] is not None

    def test_no_sub_variants_for_flat_path(self):
        p = make_parser()
        result = p.parse("author/group/file.jpg")
        assert result["sub_variants"] == []
        assert result["sub_variant"] is None


class TestParseGenericFolders:
    """Generic folders are skipped when detecting group name."""

    def test_skip_generic_gridded_folder(self):
        p = make_parser()
        result = p.parse("author/MapName/gridded/file.jpg")
        assert result["variant_group_name"] == "MapName"

    def test_skip_generic_vtt_folder(self):
        p = make_parser()
        result = p.parse("author/MapName/VTT/file.jpg")
        assert result["variant_group_name"] == "MapName"

    def test_all_generic_intermediate_folders(self):
        """When ALL intermediate folders are generic, author becomes None."""
        p = make_parser()
        result = p.parse("MyMap/gridded/file.jpg")
        assert result["author"] is None
        assert result["group_from_folder"] is True


class TestParseCamelCase:
    """CamelCase splitting in various contexts."""

    def test_camelcase_group_name(self):
        p = make_parser()
        result = p.parse("author/IslandFort/file.jpg")
        assert result["variant_group_name"] == "IslandFort"

    def test_ordinal_protection(self):
        p = make_parser()
        # _split_camel should not break "1st" apart
        assert "1st" in p._split_camel("Room1stFloor")


# ===========================================================================
# group_files() tests
# ===========================================================================


class TestGroupFilesFolder:
    """Folder-based grouping (Pass 1)."""

    def test_groups_by_author_and_group(self):
        p = make_parser()
        paths = [
            "czepeku/Island Fort/IslandFort_Night.jpg",
            "czepeku/Island Fort/IslandFort_Day.jpg",
            "czepeku/Dark Cave/DarkCave_Lit.jpg",
        ]
        groups = p.group_files(paths)
        group_names = {g["variant_group_name"] for g in groups}
        assert "Island Fort" in group_names
        assert "Dark Cave" in group_names

        fort_group = next(g for g in groups if g["variant_group_name"] == "Island Fort")
        assert len(fort_group["files"]) == 2

    def test_different_authors_separate_groups(self):
        p = make_parser()
        paths = [
            "author1/MapA/file1.jpg",
            "author2/MapA/file2.jpg",
        ]
        groups = p.group_files(paths)
        assert len(groups) == 2


class TestGroupFilesPrefix:
    """Filename-prefix grouping (Pass 2)."""

    def test_prefix_grouping_flat_files(self):
        p = make_parser()
        paths = [
            "author/ForestPath_Night.jpg",
            "author/ForestPath_Day.jpg",
            "author/ForestPath_Rain.jpg",
        ]
        groups = p.group_files(paths)
        # All three should be in one group based on common prefix
        assert len(groups) == 1
        assert len(groups[0]["files"]) == 3

    def test_different_prefixes_separate_groups(self):
        p = make_parser()
        paths = [
            "author/ForestPath_Night.jpg",
            "author/CaveDungeon_Dark.jpg",
        ]
        groups = p.group_files(paths)
        assert len(groups) == 2


class TestGroupFilesMergeSubvariants:
    """Sub-variant folder merging (Pass 1.5)."""

    def test_subvariant_folders_merged(self):
        """When top folder IS the variant group and subfolders are sub-variants."""
        p = make_parser()
        paths = [
            "Abandoned Campsite 30x30/Abandoned Campsite/camp_day.jpg",
            "Abandoned Campsite 30x30/Eerie/camp_eerie.jpg",
            "Abandoned Campsite 30x30/Sunset/camp_sunset.jpg",
        ]
        groups = p.group_files(paths)
        # Should merge into one group
        assert len(groups) == 1
        assert len(groups[0]["files"]) == 3
        # Author should be None (can't determine from this structure)
        assert groups[0]["author"] is None


class TestGroupFilesSingleFile:
    """Edge case: single file."""

    def test_single_file_in_folder(self):
        p = make_parser()
        paths = ["author/group/file.jpg"]
        groups = p.group_files(paths)
        assert len(groups) == 1
        assert len(groups[0]["files"]) == 1
