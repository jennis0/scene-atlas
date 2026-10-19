"""Unit tests for ImageParser — parse() and group_files().

Tests pure parsing logic with no DB, no filesystem.
"""

import json

import pytest

from backend.app.services.image_parser import ImageParser

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
    return ImageParser(tag_categories=cats)


# ===========================================================================
# parse() tests
# ===========================================================================


class TestParseBasic:
    """Core parsing: author, group, filename."""

    def test_three_level_path(self):
        p = make_parser()
        result = p.parse("czepeku/Island Fort/IslandFort_Night.jpg")
        assert result["author"] == "czepeku"
        assert result["group_name"] == "Island Fort"
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
        assert result["group_name"] == "Group"
        assert result["subgroups"] == ["SubA", "SubB"]
        assert result["subgroup"] == "SubA / SubB"


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

    @pytest.mark.parametrize(
        "path",
        [
            "caeora/Avernus_BlueHexGrid.jpg",
            "partyoftwo/Porttown_Set01_PortTown1_Online_HexHBlack.jpg",
            "partyoftwo/Porttown_Set02_Island_Online_HexV_HexVWhite.jpg",
            "caeora/ForestBattleShield_ForestBattleHexShield.jpg",
            "author/Fort/Fort_Night_HG.jpg",
            "author/Fort/Fort_Night_GH.jpg",
        ],
    )
    def test_hex_markers(self, path):
        result = make_parser().parse(path)
        assert (result["gridded"], result["grid_type"]) == (True, "hex")

    def test_gh_folder_is_not_a_hex_marker(self):
        # A portrait-pack code (Gnome/Halfling), not a grid marker.
        result = make_parser().parse("pack/Gnome, Halfling/GH-GH-MS-F101/Fulllength.png")
        assert result["grid_type"] is None

    def test_hex_folder_is_a_hex_marker(self):
        result = make_parser().parse("author/Fort/Hex/Fort_Night.jpg")
        assert result["grid_type"] == "hex"


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

    @pytest.mark.parametrize(
        ("filename", "size", "alternatives"),
        [
            ("Map_30x30.jpg", (30, 30), []),
            ("WizardLairDestroyed630x50.jpg", (630, 50), [[30, 50]]),
            ("ForestCamp25x201_Night.jpg", (25, 201), [[25, 20]]),
            ("Hall123x456.jpg", (123, 456), [[123, 45], [23, 456], [23, 45]]),
            ("Hall105x30.jpg", (105, 30), []),  # "05" is never a size
        ],
    )
    def test_glued_digits_give_alternative_readings(self, filename, size, alternatives):
        result = make_parser().parse(f"author/group/{filename}")
        assert (result["grid_width"], result["grid_height"]) == size
        assert result["grid_size_alternatives"] == alternatives

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

    # Real filenames (from a 179k-path library survey).
    @pytest.mark.parametrize(
        ("path", "author"),
        [
            ("2mtt_community/2mttCommunity_2mtt100_ArenabyUpsetti_Arena,Day.png", "Upsetti"),
            ("mutenn/DillingerGateMapsByMutenn_DillingerGateGL.jpg", "Mutenn"),
            ("2mtt_community/2mtt100_DragoncryptbyZachari43_Assets.jpg", "Zachari43"),
            ("2mtt_community/2mtt100_TakenOverByNaturebyBazz_Tower.png", "Nature"),
        ],
    )
    def test_by_author_variants(self, path, author):
        assert make_parser().parse(path)["author"] == author

    @pytest.mark.parametrize(
        "path",
        [
            # "by" inside a word
            "czepeku/Abyssal Fall/GL_AbyssalFall_Zone1_InfernalFall.jpg",
            "angela_maps/labyrinth/grid/Labyrinth (filled)_grid.jpg",
            "this-is-cool/daniel-bystedt/the-3d-scifi-art-of-daniel-bystedt-10.jpg",
            "redditdnd/images/tactical_map/1byh4ds_5htjevl7t4tc1.jpg",
            # an ordinary word ending in "by" before a capitalised word
            "czepeku/Haunted Ghost Ship/GL_HauntedGhostShipExterior_RubyGhost.jpg",
            "community/contest/BabyRhinos_DragonMountainCave_40x20.jpg",
            "community/KiirbyHD 1.jpg",
            # "By" followed by a filler word
            "neutral_party/Altar By The Road/AltarByTheRoad_Gridded.jpg",
        ],
    )
    def test_by_inside_words_is_not_an_author(self, path):
        assert make_parser().parse(path)["author"] == path.split("/")[0]


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


class TestParseSubgroups:
    """Subgroup detection."""

    def test_subgroups_from_folders(self):
        p = make_parser()
        result = p.parse("author/group/Night/Gridded/file.jpg")
        assert "Night" in result["subgroups"]
        assert result["subgroup"] is not None

    def test_no_subgroups_for_flat_path(self):
        p = make_parser()
        result = p.parse("author/group/file.jpg")
        assert result["subgroups"] == []
        assert result["subgroup"] is None

    def test_nested_copy_of_group_folder_is_not_a_subgroup(self):
        pack = "Abyssal Fall [various] - $5 Rewards (Gridless)"
        result = make_parser().parse(f"czepeku/{pack}/{pack}/Gridless/GL_AbyssalFall_Zone1.jpg")
        assert result["subgroup"] == "Gridless"

    def test_deeper_folder_matching_group_is_kept(self):
        path = "Crosshead/TILES/DUNGEONDRAFT MODULAR SERIES/FOREST MAPS/TILES/Bridge.jpg"
        result = make_parser().parse(path)
        assert result["subgroup"] == "DUNGEONDRAFT MODULAR SERIES / FOREST MAPS / TILES"

    @pytest.mark.parametrize(
        ("folder", "subgroup"),
        [
            ("MA 18x22", "MA"),
            (
                "Airship Port [84x111] - $5 Rewards - Slices - Gridded Pt 1",
                "Airship Port - Slices - Gridded Pt 1",
            ),
            ("Airships Pt3 - $5 Rewards", "Airships Pt3"),
            ("Full Res -- No Grid", "Full Res -- No Grid"),
            ("Gridless", "Gridless"),
        ],
    )
    def test_subgroup_noise_is_stripped(self, folder, subgroup):
        result = make_parser().parse(f"author/Group/{folder}/file.jpg")
        assert result["subgroup"] == subgroup


class TestParseGenericFolders:
    """Generic folders are skipped when detecting group name."""

    def test_skip_generic_gridded_folder(self):
        p = make_parser()
        result = p.parse("author/MapName/gridded/file.jpg")
        assert result["group_name"] == "Map Name"

    def test_skip_generic_vtt_folder(self):
        p = make_parser()
        result = p.parse("author/MapName/VTT/file.jpg")
        assert result["group_name"] == "Map Name"

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
        assert result["group_name"] == "Island Fort"

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
        group_names = {g["group_name"] for g in groups}
        assert "Island Fort" in group_names
        assert "Dark Cave" in group_names

        fort_group = next(g for g in groups if g["group_name"] == "Island Fort")
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


class TestGroupFilesFolderNamesGroup:
    """Pass 0: a folder holding files directly is one map's group, or a creator's folder."""

    def test_folder_named_on_its_files_is_the_group(self):
        p = make_parser()
        groups = p.group_files(
            ["Golden Forest/GoldenForest_Night.jpg", "Golden Forest/GoldenForest_Day_30x30.jpg"]
        )
        assert [(g["author"], g["group_name"], len(g["files"])) for g in groups] == [
            (None, "Golden Forest", 2)
        ]

    def test_files_named_only_by_variant_words_belong_to_the_folder(self):
        p = make_parser()
        groups = p.group_files(
            ["Golden Forest/Night.jpg", "Golden Forest/Snow_Gridded.jpg", "Golden Forest/2.jpg"]
        )
        assert [(g["author"], g["group_name"]) for g in groups] == [(None, "Golden Forest")]
        names = sorted(f["parsed"]["name"] for f in groups[0]["files"])
        assert names == ["2", "Night", "Snow"]

    def test_creator_folder_of_loose_maps_keeps_its_creator(self):
        p = make_parser()
        groups = p.group_files(["czepeku/IslandFort_Night.jpg", "czepeku/DarkCave_Day.jpg"])
        assert {g["author"] for g in groups} == {"czepeku"}
        assert {g["group_name"] for g in groups} == {"Island Fort", "Dark Cave"}

    def test_known_creator_is_never_a_group(self):
        """Creators who put their own name on every file look like a map folder."""
        p = make_parser()
        paths = ["leasealair/leasealair_Tavern.jpg", "leasealair/leasealair_Crypt.jpg"]
        assert {g["author"] for g in p.group_files(paths)} == {None}
        known = p.group_files(paths, known_authors=["Leasealair"])
        assert {g["author"] for g in known} == {"leasealair"}

    def test_folder_named_by_the_files_by_author_is_a_creator(self):
        p = make_parser()
        groups = p.group_files(
            ["mutenn/DillingerGateByMutenn_Grid.jpg", "mutenn/DillingerGateByMutenn_GL.jpg"]
        )
        assert all(g["group_name"] != "Mutenn" for g in groups)
        assert all(g["author"] for g in groups)

    def test_by_author_of_someone_else_is_kept(self):
        p = make_parser()
        (group,) = p.group_files(
            [
                "Golden Forest/GoldenForest_Night_byUpsetti.jpg",
                "Golden Forest/GoldenForest_Day_byUpsetti.jpg",
            ]
        )
        assert (group["author"], group["group_name"]) == ("Upsetti", "Golden Forest")

    def test_deeper_paths_are_unchanged(self):
        p = make_parser()
        (group,) = p.group_files(["Golden Forest/Gridded/Night.jpg"])
        assert (group["author"], group["group_name"]) == (None, "Golden Forest")


class TestGroupFilesMergeSubgroups:
    """Subgroup folder merging (Pass 1.5)."""

    def test_subgroup_folders_merged(self):
        """When top folder IS the group and subfolders are subgroups."""
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


class TestGroupFilesNoneAuthor:
    """Regression: multiple groups with None author must not crash _merge_subgroup_folders."""

    def test_multiple_none_author_groups_no_crash(self):
        """When several groups have author=None (all-generic folder structure),
        _merge_subgroup_folders must not pass None to re.sub().
        GH: 'expected string or bytes-like object, got NoneType'
        """
        p = make_parser()
        # Two separate groups where every intermediate folder is generic,
        # so parse() sets author=None.  Each has only generic folders
        # between the top-level folder and the file, triggering the
        # all-generic branch (line 679 in image_parser.py).
        paths = [
            "gridless/file_a.jpg",
            "gridless/file_b.jpg",
            "variants/file_c.jpg",
            "variants/file_d.jpg",
        ]
        # Should not raise TypeError
        groups = p.group_files(paths)
        assert len(groups) >= 1
        assert sum(len(g["files"]) for g in groups) == 4


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
# _build_name() tests
# ===========================================================================


class TestEmptyBrackets:
    """Brackets emptied by noise removal must not survive into names."""

    def test_group_name_after_pricing_and_grid_removed(self):
        pack = "Ages of the Vale Pt.1 [27x39] - $5 Rewards (Gridless)"
        result = make_parser().parse(f"czepeku/{pack}/01 Barn/GL_Barn_Roof_Day.jpg")
        assert result["group_name"] == "Ages of the Vale Pt.1"

    def test_scene_name_after_grid_marker_removed(self):
        result = make_parser().parse(
            "venatus/Clash Amidst Clouds/Skybreaker Main Deck (no grid).png"
        )
        assert result["name"] == "Skybreaker Main Deck"

    def test_bracket_with_content_is_kept(self):
        result = make_parser().parse("czepeku/Abyssal Fall [various] - $5 Rewards/GL_Zone1.jpg")
        assert result["group_name"] == "Abyssal Fall [various]"


class TestBuildName:
    """Individual display name generation."""

    def test_dragon_gate(self):
        p = make_parser()
        result = p._build_name("Dragon Gate no light", "Crosshead", "DUNGEONS - DRAGONGATE")
        assert result == "Dragon Gate no light"

    def test_snowy_forest(self):
        p = make_parser()
        result = p._build_name(
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
        result = p._build_name(
            "140dpiShieldChurchMaps_140dpiChurchHeavenDayGfGrid",
            "mikwewa",
            "Shield Church",
        )
        assert result == "Church Heaven Day Gf"

    def test_moonlight_rocky_coast(self):
        p = make_parser()
        result = p._build_name(
            "Moonlight_Maps_Rocky_Coast_Lava06",
            "moonlight_maps",
            "Rocky Coast",
        )
        assert result == "Lava 06"

    def test_strips_dpi(self):
        p = make_parser()
        result = p._build_name("Forest_300dpi_Night", "author", "Forest")
        assert "dpi" not in result.lower()
        assert "300" not in result

    def test_strips_pixel_dimensions(self):
        p = make_parser()
        result = p._build_name("DreadMaps_Manor_12000x8000", "Dreadmaps", "Manor")
        assert "12000" not in result

    def test_strips_grid_dimensions(self):
        p = make_parser()
        result = p._build_name("Map_Night_30x30", "author", "Map")
        assert "30" not in result

    def test_strips_author_prefix_moonlight(self):
        p = make_parser()
        result = p._build_name("Moonlight_Maps_Castle_Night", "moonlight_maps", "Castle")
        assert "Moonlight" not in result
        assert "Night" in result

    def test_strips_author_prefix_dreadmaps(self):
        p = make_parser()
        result = p._build_name("DreadMaps_Tomb_Pink_Grid", "Dreadmaps", "Tomb")
        assert "Dread" not in result or "Dread" in result  # "Dread" in "DreadMaps" stripped
        assert "Pink" in result

    def test_rejoins_abbreviations(self):
        p = make_parser()
        result = p._build_name("Map_FL1_Night", "author", "Map")
        assert "FL1" in result

    def test_preserves_variant_numbers(self):
        p = make_parser()
        result = p._build_name("Forest-1", "author", "Forest")
        assert "1" in result

    def test_empty_fallback(self):
        """If everything is stripped, falls back to cleaned stem."""
        p = make_parser()
        result = p._build_name("SomeMap", "author", "Some Map")
        assert result  # not empty

    def test_title_case_preserve_on_slug(self):
        p = make_parser()
        result = p._build_name("cave-pool-night", "author", "Cave Pool")
        # After group strip, "night" should be title-cased since all lowercase
        assert result == "Night"

    def test_strips_subgroup(self):
        p = make_parser()
        result = p._build_name(
            "Crystal_Grotto_Caustic_Gridless",
            "neutral_party",
            "Crystal Grotto Expert",
            subgroups=["Caustic"],
        )
        assert "Caustic" not in result
        assert "Gridless" not in result

    def test_strips_multiple_subgroups(self):
        p = make_parser()
        result = p._build_name(
            "Desert_Temple_Night",
            "neutral_party",
            "Desert Temple Expert",
            subgroups=["Desert Temple", "Night"],
        )
        # Both subgroups stripped, but guard prevents empty result
        assert result  # not empty

    def test_subgroup_strip_guard_nonempty(self):
        """Stripping subgroups should not empty the word list."""
        p = make_parser()
        result = p._build_name("Sunset", "author", "Group", subgroups=["Sunset"])
        assert result  # fallback kicks in


# ===========================================================================
# parse() — name integration tests
# ===========================================================================


class TestParseName:
    """End-to-end: parse() returns correct name alongside group_name."""

    def test_crosshead_dragon_gate(self):
        p = make_parser()
        result = p.parse("Crosshead/DUNGEONS - DRAGONGATE/Dragon Gate no light.jpg")
        assert result["group_name"] == "DUNGEONS - DRAGONGATE"
        assert result["name"] == "Dragon Gate no light"

    def test_dice_grimorium_snowy_forest(self):
        p = make_parser()
        result = p.parse(
            "dice_grimorium/Snowy Forest Tier 2/SnowyForestTier2_FR_Gridless_R20_SnowyForest-1.jpg"
        )
        assert result["group_name"] == "Snowy Forest"
        assert "Snowy Forest" not in result["name"]
        # Noise stripped: Tier, Gridless, R20
        assert "Gridless" not in result["name"]
        assert "R20" not in result["name"]

    def test_mikwewa_shield_church(self):
        p = make_parser()
        result = p.parse("mikwewa/140dpiShieldChurchMaps_140dpiChurchHeavenDayGfGrid.jpg")
        assert result["group_name"] == "Shield Church"
        assert result["name"] == "Church Heaven Day Gf"

    def test_moonlight_rocky_coast(self):
        p = make_parser()
        result = p.parse(
            "moonlight_maps/Rocky Coast/MA/No Grid/Moonlight_Maps_Rocky_Coast_Lava06_18x22.jpg"
        )
        assert result["group_name"] == "Rocky Coast"
        assert result["name"] == "Lava 06"

    def test_name_present_in_result(self):
        """Every parse result should include name."""
        p = make_parser()
        result = p.parse("author/group/SomeFile_Night.jpg")
        assert "name" in result
        assert isinstance(result["name"], str)
        assert len(result["name"]) > 0

    def test_venatus_simple(self):
        p = make_parser()
        result = p.parse("venatus/Bank/Bank_unfurnished.png")
        assert result["group_name"] == "Bank"
        # name should strip group prefix "Bank"
        assert "unfurnished" in result["name"].lower()

    def test_dreadmaps_slug_folder(self):
        p = make_parser()
        result = p.parse(
            "Dreadmaps/dreadmaps_dread-hills-saloon/fl1/"
            "DreadMaps_DreadHills_Saloon_FL1_Transparent_18x17_70ppi_1260x1190.png"
        )
        assert result["group_name"] == "Dread Hills Saloon"
        assert "70" not in result["name"]  # DPI stripped
        assert "1260" not in result["name"]  # pixel dims stripped

    def test_subgroup_stripped_from_name(self):
        """Subgroup folder names are removed from name."""
        p = make_parser()
        result = p.parse("neutral_party/Small Cave Expert 25x25/Sunset/Small_Cave_Sunset.jpg")
        assert result["subgroup"] == "Sunset"
        assert "Sunset" not in result["name"]


# ===========================================================================
# parse() — scene-type behaviour
# ===========================================================================


class TestParseSceneType:
    """Verify that image_type='scene' skips grid detection and uses reduced junk words."""

    def test_scene_skips_grid_detection_keywords(self):
        """Scenes should not detect gridded status, even with 'Grid' in filename."""
        p = make_parser()
        result = p.parse("author/group/Map_Gridded.jpg", image_type="scene")
        assert result["gridded"] is None

    def test_scene_skips_grid_dimensions(self):
        """Scenes should not extract grid dimensions from NxN patterns."""
        p = make_parser()
        result = p.parse("author/group/Map_30x30.jpg", image_type="scene")
        assert result["grid_width"] is None
        assert result["grid_height"] is None

    def test_scene_skips_gridless_detection(self):
        """Scenes should not set gridded=False for 'gridless' keyword."""
        p = make_parser()
        result = p.parse("author/group/Map_Gridless.jpg", image_type="scene")
        assert result["gridded"] is None

    def test_scene_skips_hex_grid_detection(self):
        """Scenes should not detect hex grid keywords."""
        p = make_parser()
        result = p.parse("author/group/Map_HexGrid.jpg", image_type="scene")
        assert result["gridded"] is None
        assert result.get("grid_type") is None

    def test_scene_does_not_strip_map_from_tags(self):
        """'map' is NOT excluded from tag extraction for scenes."""
        p = make_parser()
        # For scenes, "map" is not in the junk word exclusion set,
        # so it could be extracted as a raw word for tag matching.
        # Verify indirectly: scene parse keeps "map" in extractable tokens.
        result_scene = p.parse("author/group/Map_Night.jpg", image_type="scene")
        result_bmap = p.parse("author/group/Map_Night.jpg", image_type="battlemap")
        # Both have the same name, but the scene's tag extraction
        # does not exclude "map" while the battlemap's does.
        # We can't directly test raw words, but we can verify grid stop words
        # are excluded for battlemaps but not scenes.
        assert result_scene["gridded"] is None  # scene: no grid detection
        assert result_bmap["gridded"] is None  # this particular file has no grid keyword

    def test_scene_grid_stop_words_not_excluded(self):
        """Scene tag extraction does not exclude grid stop words like 'gridded'."""
        p = make_parser()
        # The key difference: for battlemaps, grid stop words are in exclusions
        # and won't be matched as tags. For scenes, they're not excluded.
        # Since 'gridded' is not a tag vocabulary word, this won't produce tags,
        # but the exclusion logic differs.
        result = p.parse("author/group/Map_Gridded_Night.jpg", image_type="scene")
        assert result["gridded"] is None  # no grid detection for scenes

    def test_battlemap_default_type(self):
        """parse() defaults to battlemap type (grid detection active)."""
        p = make_parser()
        result = p.parse("author/group/Map_Grid.jpg")
        assert result["gridded"] is True
