"""Rule-level tests of the walk (variant_grouping.walk), through the public API."""

import dataclasses

from backend.app.services.variant_grouping import (
    FolderReason,
    GroupingFile,
    GroupingParams,
    group_with_content,
)

from .support import (
    CONTENT_PARAMS,
    Look,
    Scenario,
    by_prefix,
    group_of,
    parser,
    run_content,
    run_paths,
)


def files(paths: list[str]) -> list[GroupingFile[str]]:
    return [GroupingFile(p, p) for p in paths]


ROOM_NAMES = ["Armory", "Scriptorium", "Chapel", "Kitchen", "Barracks", "Gatehouse", "Treasury"]
ROOM_NAMES += ["Stables", "Forge"]


def rooms(parent: str, n: int, theme: str = "one location") -> Scenario:
    """``n`` rooms of one location, each its own folder of two variants."""
    out = {}
    for name in ROOM_NAMES[:n]:
        for v, variant in enumerate(["Day", "Night"]):
            out[f"{parent}/{name}/{name}_{variant}.jpg"] = Look(name, theme, variant=v)
    return Scenario(out)


class TestContainers:
    def test_meaningful_parent_joins_its_rooms_as_subgroups(self):
        g = run_content(rooms("Maker/Castle Keep", 4))
        assert len(g.groups) == 1
        assert set(g.groups[0].subgroups.values()) == {"Armory", "Scriptorium", "Chapel", "Kitchen"}
        assert "c1 parent+cohesion" in g.groups[0].reasons

    def test_many_rooms_of_one_place_join(self):
        """How many units a folder holds never makes it a container (scale invariance): nine
        rooms of one production under a specific parent are one map."""
        g = run_content(rooms("Maker/Castle Keep", 9))
        assert len(g.groups) == 1 and "c1 parent+cohesion" in g.groups[0].reasons
        assert g.folders[("maker", "castle keep")].reason is FolderReason.LOCATION

    def test_over_the_safety_cap_is_a_container(self):
        """More than ``max_units`` units: a container, unless the whole folder is cohesive
        (c0). Two themes here, so units sharing one stay apart too."""
        scenario = rooms("Maker/Castle Keep", 9)
        scenario.files = {
            p: dataclasses.replace(look, theme="other" if p < "Maker/Castle Keep/G" else "one")
            for p, look in scenario.files.items()
        }
        g = run_content(scenario, dataclasses.replace(CONTENT_PARAMS, max_units=8))
        assert len(g.groups) == 9
        assert g.folders[("maker", "castle keep")].reason is FolderReason.OVER_CAP

    def test_cohesive_folder_over_the_cap_joins_whole(self):
        """c0: every unit shares production and theme, and child folders give the structural
        evidence."""
        g = run_content(
            rooms("Maker/Castle Keep", 9), dataclasses.replace(CONTENT_PARAMS, max_units=8)
        )
        assert len(g.groups) == 1 and "c0 whole-folder" in g.groups[0].reasons
        assert not g.folders[("maker", "castle keep")].container

    def test_pack_of_different_productions_is_a_container(self):
        """A folder holding only self-contained maps (each a variant set in its own folder)
        drawn to different canvases is a pack: its maps never join, however alike."""
        out = {}
        for name, size in (("Mages Observatory", 2775), ("Volcanic Dungeon", 3330)):
            for v, variant in enumerate(["Day", "Night"]):
                path = f"Maker/{name}/{name.replace(' ', '_')}_{variant}.jpg"
                out[path] = Look(name, "one style", v, pixels=(size, size))
        g = run_content(Scenario(out))
        assert len(g.groups) == 2
        assert g.folders[("maker",)].reason is FolderReason.PACK

    def test_children_of_one_production_are_a_candidate_location(self):
        """The same children on one canvas: not a pack, so the parent can join them (c1)."""
        out = {}
        for name in ("Upper Deck", "Lower Deck"):
            for v, variant in enumerate(["Day", "Night"]):
                path = f"Maker/Airship/{name}/{name.replace(' ', '_')}_{variant}.jpg"
                out[path] = Look(name, "airship", v, pixels=(3000, 3000))
        g = run_content(Scenario(out))
        assert len(g.groups) == 1
        assert not g.folders[("maker", "airship")].container

    def test_parent_needs_a_shared_canvas(self):
        """c1: rooms drawn to different canvases are different maps, even under a specific
        parent with files of its own (so not a pack)."""
        out = {
            "Maker/Castle Keep/Castle_Keep_Overview.jpg": Look(
                "overview", "keep", pixels=(900, 900)
            )
        }
        for name, size in (("Armory", 2775), ("Chapel", 3330)):
            for v, variant in enumerate(["Day", "Night"]):
                path = f"Maker/Castle Keep/{name}/{name}_{variant}.jpg"
                out[path] = Look(name, "keep", v, pixels=(size, size))
        g = run_content(Scenario(out))
        armory = group_of(g, "Maker/Castle Keep/Armory/Armory_Day.jpg")
        assert "Maker/Castle Keep/Chapel/Chapel_Day.jpg" not in armory.keys
        assert len(g.groups) == 3

    def test_known_author_folder_is_a_container(self):
        """A folder named after a creator in the library is the author, never a map: alone it
        would be a candidate location whose cohesive children join."""
        scenario = rooms("Czepeku", 2)
        assert len(run_content(scenario).groups) == 1
        g = run_content(scenario, known_authors=["Czepeku"])
        assert len(g.groups) == 2
        assert g.folders[("czepeku",)].reason is FolderReason.KNOWN_AUTHOR

    def test_a_subtree_groups_the_same_alone(self):
        """Scale invariance: a maker folder groups the same imported alone as inside a larger
        import with other makers' folders."""
        alone = rooms("Maker/Castle Keep", 3)
        alone.files["Maker/Ruined_Tower_Day.jpg"] = Look("tower", "ruin")
        alone.files["Maker/Ruined_Tower_Night.jpg"] = Look("tower", "ruin", variant=1)
        bigger = Scenario(dict(alone.files))
        for k in range(12):
            for v, variant in enumerate(["Day", "Night"]):
                path = f"Other Maker/Map {k:02d}/Map_{k:02d}_{variant}.jpg"
                bigger.files[path] = Look(f"other {k}", variant=v)
        inside = {frozenset(grp.keys) & set(alone.files) for grp in run_content(bigger).groups} - {
            frozenset()
        }
        assert inside == {frozenset(grp.keys) for grp in run_content(alone).groups}

    def test_generic_name_is_a_container(self):
        g = run_content(rooms("Maker/Pack 03", 3))
        assert len(g.groups) == 3
        assert g.folders[("maker", "pack 03")].reason is FolderReason.GENERIC

    def test_cohesion_gates_the_parent(self):
        """Different maps under a specific parent (a same-maker pack): no theme, no join."""
        scenario = rooms("Maker/Castle Keep", 3)
        scenario.files = {
            p: dataclasses.replace(look, theme=look.layout) for p, look in scenario.files.items()
        }
        assert len(run_content(scenario).groups) == 3

    def test_parent_needs_content(self):
        """Paths only: the parent rule is content-gated, so it is withheld."""
        g = run_paths(rooms("Maker/Castle Keep", 4).grouping_files())
        assert len(g.groups) == 4


class TestNameRules:
    def test_same_name_joins(self):
        g = run_paths(files(["M/F/ForestRoad_Day.jpg", "M/F/Forest_Road_Night_Gridless.jpg"]))
        assert len(g.groups) == 1 and "a2 same-name" in g.groups[0].reasons

    def test_levels_join_as_floors_of_one_map(self):
        g = run_paths(
            files([f"2mtt/Abandoned House - {lv} - 8x6.png" for lv in ("Floor 1", "Floor 2")])
        )
        assert len(g.groups) == 1
        assert set(g.groups[0].subgroups.values()) == {"Floor 1", "Floor 2"}

    def test_numbered_family_carries_no_name(self):
        """``IMG_0001`` ... are a numbering, not one map."""
        g = run_paths(files([f"Camera/IMG_{k:04d}.jpg" for k in range(8)]))
        assert len(g.groups) == 8

    def test_shared_base_joins_a_small_family(self):
        g = run_paths(files([f"Flat Pack/Forest_Road_{w}.jpg" for w in ("Bridge", "Camp")]))
        assert len(g.groups) == 1 and "a4 shared-base" in g.groups[0].reasons

    def test_shared_base_over_a_big_family_needs_cohesion(self):
        """A shared base over > 8 units looks like a collection."""
        words = ["bridge", "camp", "gate", "ruins", "well", "shrine", "mill", "pond", "lake"]
        paths = [f"Library/Pack/Forest Road {w.title()}/Forest_Road_{w}.jpg" for w in words]
        assert len(run_paths(files(paths)).groups) == 9

    def test_folder_named_after_its_files_is_one_map(self):
        """The folder is named after its files' common tokens and only variant words remain:
        one map."""
        paths = [
            f"Moonlight Maps/Forest Switch Maps/MA 1/Grid/Moonlight_Maps_Forest_Switch_{w}_25x25.jpg"
            for w in ("Six101", "Five17", "Three05")
        ]
        g = run_paths(files(paths))
        assert len(g.groups) == 1
        assert g.folders[("moonlight maps", "forest switch maps")].named_after_files

    def test_unnamed_parts_join_a_named_map(self):
        """b5: ``Isolated Floors/1st_Floor.png`` inside Roadside Watchtower."""
        base = "Neutral Party/Roadside Watchtower Expert 30x26"
        paths = [f"{base}/Roadside_Watchtower{v}.jpg" for v in ("", "_Night", "_Foggy")]
        paths += [f"{base}/Isolated Floors/{k}_Floor.png" for k in ("1st", "2nd", "3rd")]
        g = run_paths(files(paths))
        assert len(g.groups) == 1
        assert "b5 unnamed parts" in g.groups[0].reasons
        assert set(g.groups[0].subgroups.values()) == {"Isolated Floors"}


class TestVariantOnlyFolders:
    """a6: a named folder of files named only by variant words is one map."""

    def test_variant_only_files_in_a_named_folder_join_by_path(self):
        """``Golden Forest/Night.webp`` ... is one map, as the parser's ``group_files`` has it."""
        g = run_paths(files([f"Golden Forest/{v}.webp" for v in ("Night", "Day", "Snow")]))
        assert len(g.groups) == 1
        assert "a6 variant-only folder" in g.groups[0].reasons
        assert g.groups[0].name == "Golden Forest"

    def test_variant_only_files_under_a_slug_folder(self):
        """Czepeku-style raw downloads: ``secluded-tea-valley/fog.webp``."""
        slugs = ("secluded-tea-valley", "yggdrasil-roots")
        paths = [f"Czepeku/{s}/{v}.webp" for s in slugs for v in ("fog", "rain", "day-dark")]
        g = run_paths(files(paths))
        assert sorted(grp.name for grp in g.groups) == ["Secluded Tea Valley", "Yggdrasil Roots"]

    def test_variant_only_files_in_a_generic_folder_stay_apart(self):
        g = run_paths(files([f"Maps/{v}.webp" for v in ("Night", "Day", "Snow")]))
        assert len(g.groups) == 3

    def test_counter_names_are_not_variant_only(self):
        """Photos in a named folder (``Keep/IMG_001.jpg``) are not one map by a6."""
        g = run_paths(files([f"Keep Photos/IMG_00{k}.jpg" for k in (1, 2, 3)]))
        assert len(g.groups) == 3

    def test_variant_only_needs_most_files_unnamed(self):
        paths = ["Golden Forest/Night.webp", "Golden Forest/Desert_Camp.webp"]
        paths += ["Golden Forest/Forest_Ruins.webp", "Golden Forest/Day.webp"]
        assert len(run_paths(files(paths)).groups) == 4

    def test_variant_only_content_join_still_works(self):
        scenario = Scenario(
            {f"Maps/{v}.webp": Look("golden forest", variant=k) for k, v in enumerate(
                ["Night", "Day", "Snow"])}
        )  # fmt: skip
        g = run_content(scenario)
        assert len(g.groups) == 1 and "a3 same-layout" in g.groups[0].reasons


class TestLevelsAndRooms:
    def test_one_word_map_floors_join_with_level_subgroups(self):
        """``Inn_Basement``, ``Inn_Roof``, ``Inn_Floor1``: one map "Inn", three floors."""
        paths = [f"Tavern Pack/Inn_{lv}.png" for lv in ("Basement", "Roof", "Floor1")]
        g = run_paths(files(paths))
        assert len(g.groups) == 1
        assert g.groups[0].name == "Inn"
        assert set(g.groups[0].subgroups.values()) == {"Basement", "Roof", "Floor 1"}

    def test_one_word_keys_do_not_join_otherwise(self):
        paths = [f"Tavern Pack/Inn_{w}.png" for w in ("Bridge", "Camp", "Harbour")]
        assert len(run_paths(files(paths)).groups) == 3

    def test_library_folder_is_a_room(self):
        """``Library`` / ``Old Library`` name rooms, not generic folders."""
        scenario = rooms("Maker/Castle Keep", 3)
        scenario.files |= {
            f"Maker/Castle Keep/Old Library/Old_Library_{v}.jpg": Look(
                "Old Library", "one location", k
            )
            for k, v in enumerate(["Day", "Night"])
        }
        g = run_content(scenario)
        assert len(g.groups) == 1
        assert "Old Library" in set(g.groups[0].subgroups.values())
        assert not g.folders[("maker", "castle keep", "old library")].container


class TestContentRules:
    def test_agreement_never_joins_against_names(self):
        """Same layout, but two variant sets whose names carry different keys: two maps (a3 is
        vetoed, and the leaf default sees distinct names on both sides)."""
        scenario = Scenario(
            {
                f"M/Flat/{name}_{variant}.jpg": Look("one layout", variant=2 * k + v)
                for k, name in enumerate(("Forest_Road", "Desert_Camp"))
                for v, variant in enumerate(["Day", "Night"])
            }
        )
        assert len(run_content(scenario).groups) == 2

    def test_renditions_join_across_the_tree(self):
        """x1: a rendition anywhere joins (narrow mode)."""
        scenario = Scenario(
            {
                "Downloads/Patreon Oct/forest_road_final.jpg": Look("forest road"),
                "Backup/Old Stuff/ForestRoadCopy.jpg": Look("forest road", rendition=1),
            }
        )
        g = run_content(scenario)
        assert len(g.groups) == 1 and "x1 rendition" in g.groups[0].reasons

    def test_renditions_between_two_large_groups_are_a_suggestion(self):
        """x1 between two groups both ``big_join`` large: a suggestion, never a join."""
        out = {}
        for maker, name in (("Kraken Maker", "Kraken Cove"), ("Dragon Maker", "Dragon Peak")):
            for v, variant in enumerate(["Day", "Night", "Winter", "Summer"]):
                out[f"{maker}/{name}/{name.replace(' ', '_')}_{variant}.jpg"] = Look(
                    name, variant=v
                )
        # a Kraken Cove image named like Dragon Peak's files, so the name joins it there (a2)
        out["Dragon Maker/Dragon Peak/Dragon_Peak_Fog.jpg"] = Look("Kraken Cove", rendition=1)
        g = run_content(Scenario(out), dataclasses.replace(CONTENT_PARAMS, big_join=4))
        assert len(g.groups) == 2
        assert [s.reason for s in g.suggestions] == ["rendition(two large groups)"]

    def test_a_misfiled_rendition_joins_its_own_map(self):
        """A Kraken Cove copy filed in Dragon Peak's folder under a numbered name: the folder's
        maps reject it on content (a7), and the rendition takes it to Kraken Cove (x1)."""
        out = {}
        for maker, name in (("Kraken Maker", "Kraken Cove"), ("Dragon Maker", "Dragon Peak")):
            for k in range(20):
                out[f"{maker}/{name}/{name.replace(' ', '_')}_v{k}.jpg"] = Look(name, variant=k)
        out["Dragon Maker/Dragon Peak/Dragon_Peak_v99.jpg"] = Look("Kraken Cove", rendition=1)
        g = run_content(Scenario(out))
        kraken = group_of(g, "Kraken Maker/Kraken Cove/Kraken_Cove_v0.jpg")
        assert "Dragon Maker/Dragon Peak/Dragon_Peak_v99.jpg" in kraken.keys
        assert len(g.groups) == 2 and "x1 rendition" in kraken.reasons

    def test_missing_features_withhold_content_joins(self):
        """A room without features takes part through names and folders only."""
        scenario = rooms("Maker/Castle Keep", 3)
        content = scenario.content()
        for path in by_prefix(content.keys(), "Maker/Castle Keep/Chapel/"):
            # its size is still known (every image has one), so the children share production
            content[path] = dataclasses.replace(
                content[path], phash256=None, edge=None, embedding=None
            )
        g = group_with_content(scenario.grouping_files(), content, CONTENT_PARAMS, parser())
        assert len(g.groups) == 2
        chapel = group_of(g, "Maker/Castle Keep/Chapel/Chapel_Day.jpg")
        assert len(chapel.keys) == 2  # still joined by its name

    def test_embedding_rules_off_without_calibration(self):
        """No calibration for the encoder: renditions still join, the parent rule does not."""
        scenario = rooms("Maker/Castle Keep", 3)
        scenario.files["Maker/Castle Keep/Armory/Armory_Print.jpg"] = Look(
            "Armory", "one location", rendition=1
        )
        g = run_content(scenario, GroupingParams(embedding=None))
        assert len(g.groups) == 3
        assert "a1 rendition" in group_of(g, "Maker/Castle Keep/Armory/Armory_Print.jpg").reasons

    def test_whole_folder_joins_a_cohesive_named_folder(self):
        """c0 (Limithron Coral Reef): colour variants that only content can join, in a folder
        named after its files."""
        base = "limithron/Limithron Coral Reef Shipwreck Battlemap 45x45"
        out = {}
        for colour in ["Blighted", "Blue-Hole", "Tide-Pool-Ghost-Ship", "Sunken-Wreck"]:
            for grid, suffix in (("Gridded", "Grid"), ("No Grid", "NoGrid")):
                path = f"{base}/{grid}/Limithron-Coral-Reef-{colour}-45x45-{suffix}.jpg"
                out[path] = Look(f"reef {colour}", "coral reef", rendition=int(suffix == "Grid"))
        scenario = Scenario(out)
        assert len(run_paths(scenario.grouping_files()).groups) == 4
        g = run_content(scenario)
        assert len(g.groups) == 1 and "c0 whole-folder" in g.groups[0].reasons

    def test_catalog_named_single_maps_stay_apart(self):
        """A flat folder of cohesive one-image maps, each with a name of its own (dndavid): the
        names say different maps, so the leaf default keeps them apart; suggestions only."""
        names = ("Abandoned_Temple", "Arbor_Watch_Tower", "Bandit_Camp")
        out = {f"dndavid/{n}HD.jpg": Look(n, "style") for n in names}
        g = run_content(Scenario(out))
        assert len(g.groups) == 3
        assert {s.reason for s in g.suggestions} == {"cohesive, no folder/name evidence"}
        assert "a7 leaf default" not in g.decisions["dndavid"].joins


class TestLeafDefault:
    """a7: in a specific leaf folder, units join unless shown to be different maps."""

    @staticmethod
    def tavern(names: tuple[str, ...], theme: str = "tavern") -> Scenario:
        """Single images of one place, each a different scene (different layouts)."""
        return Scenario({f"Desert City Tavern/{n}.webp": Look(f"tavern {n}", theme) for n in names})

    def test_variants_named_like_maps_join(self):
        """Heavy single variants whose names read as names (``Biohazard``, ``Last_Call``): no
        strong evidence either way, so the folder decides."""
        g = run_content(self.tavern(("Biohazard", "Last_Call", "Bio_Research")))
        assert len(g.groups) == 1 and "a7 leaf default" in g.groups[0].reasons

    def test_low_cohesion_is_different(self):
        """Content that is clearly unrelated is a different map whatever the folder says."""
        scenario = self.tavern(("Biohazard", "Last_Call"))
        scenario.files["Desert City Tavern/Snowy_Pass.webp"] = Look("pass", "mountains")
        assert len(run_content(scenario).groups) == 2

    def test_needs_content(self):
        """Paths only: the leaf default is withheld (content only adds joins)."""
        assert len(run_paths(self.tavern(("Biohazard", "Last_Call")).grouping_files()).groups) == 2

    def test_series_are_different_maps(self):
        """``Volcanic Path`` and ``Volcanic Path Vol2``: one head word, different series."""
        out = {
            f"Maker/Lava Lands/{stem}_{variant}.jpg": Look(f"layout {stem}", "volcano", v)
            for stem in ("Volcanic_Path", "Volcanic_Path_Vol2", "Ash_Fields")
            for v, variant in enumerate(["Day", "Night"])
        }
        g = run_content(Scenario(out))
        assert len(g.groups) == 3
        assert "a7 leaf default" not in g.decisions["maker/lava lands"].joins

    def test_a_dominant_map_does_not_absorb_a_minority(self):
        """a5 joins only files that carry the folder's common name: ``SnowyCoast`` is a map of
        its own in a folder mostly of ``CanalCity``."""
        out = {
            f"Maker/Seaside/CanalCity_{variant}.jpg": Look("canal city", "canal", v)
            for v, variant in enumerate(["Day", "Night", "Winter", "Summer", "Rain", "Fog"])
        }
        out["Maker/Seaside/SnowyCoast_Day.jpg"] = Look("snowy coast", "coast")
        out["Maker/Seaside/SnowyCoast_Night.jpg"] = Look("snowy coast", "coast", variant=1)
        g = run_content(Scenario(out))
        assert len(g.groups) == 2
        assert len(group_of(g, "Maker/Seaside/SnowyCoast_Day.jpg").keys) == 2


def test_small_maker_folder_keeps_maps_apart():
    """Two maps of one maker whose files all start ``Moonlight_Maps_`` share the 2-token key
    ``moonlight maps``. It is only the maker folder's name, and different multi-token names
    follow it, so it is a house prefix, not a shared base."""
    paths = [
        f"Moonlight Maps/{m}/MA/Moonlight_Maps_{m.replace(' ', '_')}_{v}_18x22.jpg"
        for m in ("Forest Cottage", "Forest Switch")
        for v in ("Grass01", "Snow02_Night")
    ]
    g = run_paths(files(paths))
    assert sorted(grp.name for grp in g.groups) == ["Forest Cottage", "Forest Switch"]
    assert {grp.author for grp in g.groups} == {"Moonlight Maps"}


def test_small_flat_maker_folder_keeps_maps_apart():
    """A flat maker folder whose files share the house prefix ``Moonlight_Maps_``: the shared
    base is cohesion-gated (as folder IDF gates it inside a large import), so the variants of
    each map join on content and the two maps stay apart."""
    out = {
        f"Moonlight Maps/Moonlight_Maps_{m}_{v}_18x22.jpg": Look(m, variant=k)
        for m in ("Forest_Cottage", "Deep_Cave")
        for k, v in enumerate(("Grass01", "Snow02_Night"))
    }
    g = run_content(Scenario(out))
    assert sorted(grp.name for grp in g.groups) == ["Deep Cave", "Forest Cottage"]
    assert len(run_paths(Scenario(out).grouping_files()).groups) == 4  # the gate needs content


MONSTER_HUNTER_VARIANTS = [
    "autumn",
    "candlelight",
    "closing",
    "dark",
    "desert-day",
    "desert-night",
    "ebony-day",
    "ebony-night",
    "empty-day",
    "empty-night",
    "fighting-pit-1-day",
    "fighting-pit-1-night",
    "fighting-pit-2-night",
    "fighting-pit-3-night",
    "fighting-pit-4-night",
    "fighting-pit-5-night",
    "fireflies",
    "fog",
    "haunted",
    "massacre",
    "murder-mystery",
    "natural-day",
    "natural-night",
    "opulent-day",
    "opulent-night",
    "original-night",
    "rain",
    "spring-day",
    "spring-night",
    "winter-day",
    "winter-night",
]


def test_named_map_reads_names_before_the_prefix_strip():
    """A lone Czepeku map whose files all start ``MonsterHunterRestaurant_``: the strip reads
    ``monster hunter`` as a prefix (a hub), so the folder's name is checked against each file's
    identity with the stripped tokens put back, and a5 joins the map's files."""
    paths = [
        f"Czepeku/monster-hunter-restaurant/MonsterHunterRestaurant_{v}.webp"
        for v in MONSTER_HUNTER_VARIANTS
    ]
    g = run_paths(files(paths))
    main = group_of(g, paths[0])
    assert len(main.keys) >= 25 and "a5 folder-named" in main.reasons


def test_folder_name_followed_by_variant_words_is_the_map():
    """Only variant words follow the folder's name: the folder is the map."""
    paths = [f"Forest Road/Forest_Road_{v}.jpg" for v in ("Day", "Night", "Snow_Night")]
    assert len(run_paths(files(paths)).groups) == 1
