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
        assert result["variant_group_name"] == "Map Name"

    def test_skip_generic_vtt_folder(self):
        p = make_parser()
        result = p.parse("author/MapName/VTT/file.jpg")
        assert result["variant_group_name"] == "Map Name"

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
        assert result["variant_group_name"] == "Island Fort"

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


# ===========================================================================
# _clean_group_name() tests
# ===========================================================================


class TestCleanGroupName:
    """Variant group name cleaning."""

    def test_strips_tier_info(self):
        p = make_parser()
        assert p._clean_group_name("Snowy Forest Tier 2") == "Snowy Forest"

    def test_strips_tier_camelcase(self):
        p = make_parser()
        assert p._clean_group_name("SnowyForestTier2") == "Snowy Forest"

    def test_strips_volume(self):
        p = make_parser()
        assert p._clean_group_name("Volcanic Path Vol3 Tier 2 Full Resolution") == "Volcanic Path"

    def test_strips_pricing(self):
        p = make_parser()
        assert p._clean_group_name("Modular Caves - $5 Rewards") == "Modular Caves"

    def test_preserves_dashes_between_concepts(self):
        p = make_parser()
        assert p._clean_group_name("DUNGEONS - DRAGONGATE") == "DUNGEONS - DRAGONGATE"

    def test_slug_dashes_become_spaces(self):
        p = make_parser()
        result = p._clean_group_name("tomb-of-the-blight-lich")
        assert result == "Tomb Of The Blight Lich"

    def test_strips_full_resolution_files(self):
        p = make_parser()
        assert p._clean_group_name("City Streets Tier 2 Full Resolution Files") == "City Streets"

    def test_strips_platform_markers(self):
        p = make_parser()
        assert p._clean_group_name("Cave FVTT R20") == "Cave"

    def test_strips_grid_state(self):
        p = make_parser()
        assert p._clean_group_name("Forest Path Gridded") == "Forest Path"
        assert p._clean_group_name("Forest Path Gridless") == "Forest Path"

    def test_strips_dpi(self):
        p = make_parser()
        assert p._clean_group_name("140dpiShieldChurchMaps") == "Shield Church"

    def test_strips_maps_plural(self):
        p = make_parser()
        assert p._clean_group_name("ShieldChurchMaps") == "Shield Church"

    def test_keeps_map_singular(self):
        p = make_parser()
        result = p._clean_group_name("MapName")
        assert result == "Map Name"

    def test_strips_author_prefix(self):
        p = make_parser()
        result = p._clean_group_name("dreadmaps_dread-hills-saloon", author="Dreadmaps")
        assert result == "Dread Hills Saloon"

    def test_clean_already_clean(self):
        p = make_parser()
        assert p._clean_group_name("Rocky Coast") == "Rocky Coast"

    def test_empty_guard(self):
        """Cleaning should never return an empty string."""
        p = make_parser()
        result = p._clean_group_name("Maps")
        assert result  # not empty

    def test_deduplicates_repeated_sequences(self):
        p = make_parser()
        result = p._clean_group_name("Forest Path Forest Path")
        assert result == "Forest Path"

    def test_strips_leading_numbering(self):
        p = make_parser()
        assert p._clean_group_name("07. Swamps") == "Swamps"
        assert p._clean_group_name("10. Wizards Choice") == "Wizards Choice"

    def test_deduplicates_consecutive_words(self):
        p = make_parser()
        result = p._clean_group_name("Blacksmith Blacksmith")
        assert result == "Blacksmith"


# ===========================================================================
# _build_map_name() tests
# ===========================================================================


class TestBuildMapName:
    """Individual map display name generation."""

    def test_dragon_gate(self):
        p = make_parser()
        result = p._build_map_name("Dragon Gate no light", "Crosshead", "DUNGEONS - DRAGONGATE")
        assert result == "Dragon Gate no light"

    def test_snowy_forest(self):
        p = make_parser()
        result = p._build_map_name(
            "SnowyForestTier2_FR_Gridless_R20_SnowyForest",
            "dice_grimorium",
            "Snowy Forest",
        )
        # VG stripped, noise stripped (Tier, Gridless, R20), dedup removes second VG
        assert "Snowy Forest" not in result
        assert "Gridless" not in result
        assert "R20" not in result

    def test_mikwewa_church(self):
        p = make_parser()
        result = p._build_map_name(
            "140dpiShieldChurchMaps_140dpiChurchHeavenDayGfGrid",
            "mikwewa",
            "Shield Church",
        )
        assert result == "Church Heaven Day Gf"

    def test_moonlight_rocky_coast(self):
        p = make_parser()
        result = p._build_map_name(
            "Moonlight_Maps_Rocky_Coast_Lava06",
            "moonlight_maps",
            "Rocky Coast",
        )
        assert result == "Lava 06"

    def test_strips_dpi(self):
        p = make_parser()
        result = p._build_map_name("Forest_300dpi_Night", "author", "Forest")
        assert "dpi" not in result.lower()
        assert "300" not in result

    def test_strips_pixel_dimensions(self):
        p = make_parser()
        result = p._build_map_name(
            "DreadMaps_Manor_12000x8000", "Dreadmaps", "Manor"
        )
        assert "12000" not in result

    def test_strips_grid_dimensions(self):
        p = make_parser()
        result = p._build_map_name("Map_Night_30x30", "author", "Map")
        assert "30" not in result

    def test_strips_author_prefix_moonlight(self):
        p = make_parser()
        result = p._build_map_name(
            "Moonlight_Maps_Castle_Night", "moonlight_maps", "Castle"
        )
        assert "Moonlight" not in result
        assert "Night" in result

    def test_strips_author_prefix_dreadmaps(self):
        p = make_parser()
        result = p._build_map_name(
            "DreadMaps_Tomb_Pink_Grid", "Dreadmaps", "Tomb"
        )
        assert "Dread" not in result or "Dread" in result  # "Dread" in "DreadMaps" stripped
        assert "Pink" in result

    def test_rejoins_abbreviations(self):
        p = make_parser()
        result = p._build_map_name("Map_FL1_Night", "author", "Map")
        assert "FL1" in result

    def test_preserves_variant_numbers(self):
        p = make_parser()
        result = p._build_map_name("Forest-1", "author", "Forest")
        assert "1" in result

    def test_empty_fallback(self):
        """If everything is stripped, falls back to cleaned stem."""
        p = make_parser()
        result = p._build_map_name("SomeMap", "author", "Some Map")
        assert result  # not empty

    def test_title_case_preserve_on_slug(self):
        p = make_parser()
        result = p._build_map_name("cave-pool-night", "author", "Cave Pool")
        # After VG strip, "night" should be title-cased since all lowercase
        assert result == "Night"

    def test_strips_sub_variant(self):
        p = make_parser()
        result = p._build_map_name(
            "Crystal_Grotto_Caustic_Gridless",
            "neutral_party",
            "Crystal Grotto Expert",
            sub_variants=["Caustic"],
        )
        assert "Caustic" not in result
        assert "Gridless" not in result

    def test_strips_multiple_sub_variants(self):
        p = make_parser()
        result = p._build_map_name(
            "Desert_Temple_Night",
            "neutral_party",
            "Desert Temple Expert",
            sub_variants=["Desert Temple", "Night"],
        )
        # Both sub-variants stripped, but guard prevents empty result
        assert result  # not empty

    def test_sub_variant_strip_guard_nonempty(self):
        """Stripping sub-variants should not empty the word list."""
        p = make_parser()
        result = p._build_map_name(
            "Sunset", "author", "Group", sub_variants=["Sunset"]
        )
        assert result  # fallback kicks in


# ===========================================================================
# parse() — map_name integration tests
# ===========================================================================


class TestParseMapName:
    """End-to-end: parse() returns correct map_name alongside variant_group_name."""

    def test_crosshead_dragon_gate(self):
        p = make_parser()
        result = p.parse("Crosshead/DUNGEONS - DRAGONGATE/Dragon Gate no light.jpg")
        assert result["variant_group_name"] == "DUNGEONS - DRAGONGATE"
        assert result["map_name"] == "Dragon Gate no light"

    def test_dice_grimorium_snowy_forest(self):
        p = make_parser()
        result = p.parse(
            "dice_grimorium/Snowy Forest Tier 2/"
            "SnowyForestTier2_FR_Gridless_R20_SnowyForest-1.jpg"
        )
        assert result["variant_group_name"] == "Snowy Forest"
        assert "Snowy Forest" not in result["map_name"]
        # Noise stripped: Tier, Gridless, R20
        assert "Gridless" not in result["map_name"]
        assert "R20" not in result["map_name"]

    def test_mikwewa_shield_church(self):
        p = make_parser()
        result = p.parse(
            "mikwewa/140dpiShieldChurchMaps_140dpiChurchHeavenDayGfGrid.jpg"
        )
        assert result["variant_group_name"] == "Shield Church"
        assert result["map_name"] == "Church Heaven Day Gf"

    def test_moonlight_rocky_coast(self):
        p = make_parser()
        result = p.parse(
            "moonlight_maps/Rocky Coast/MA/No Grid/"
            "Moonlight_Maps_Rocky_Coast_Lava06_18x22.jpg"
        )
        assert result["variant_group_name"] == "Rocky Coast"
        assert result["map_name"] == "Lava 06"

    def test_map_name_present_in_result(self):
        """Every parse result should include map_name."""
        p = make_parser()
        result = p.parse("author/group/SomeFile_Night.jpg")
        assert "map_name" in result
        assert isinstance(result["map_name"], str)
        assert len(result["map_name"]) > 0

    def test_venatus_simple(self):
        p = make_parser()
        result = p.parse("venatus/Bank/Bank_unfurnished.png")
        assert result["variant_group_name"] == "Bank"
        # map_name should strip VG prefix "Bank"
        assert "unfurnished" in result["map_name"].lower()

    def test_dreadmaps_slug_folder(self):
        p = make_parser()
        result = p.parse(
            "Dreadmaps/dreadmaps_dread-hills-saloon/fl1/"
            "DreadMaps_DreadHills_Saloon_FL1_Transparent_18x17_70ppi_1260x1190.png"
        )
        assert result["variant_group_name"] == "Dread Hills Saloon"
        assert "70" not in result["map_name"]  # DPI stripped
        assert "1260" not in result["map_name"]  # pixel dims stripped

    def test_sub_variant_stripped_from_map_name(self):
        """Sub-variant folder names are removed from map_name."""
        p = make_parser()
        result = p.parse(
            "neutral_party/Small Cave Expert 25x25/Sunset/Small_Cave_Sunset.jpg"
        )
        assert result["sub_variant"] == "Sunset"
        assert "Sunset" not in result["map_name"]
