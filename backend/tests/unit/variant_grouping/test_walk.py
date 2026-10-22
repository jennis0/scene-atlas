"""Rule-level tests of the walk (variant_grouping.walk), through the public API."""

import dataclasses

from backend.app.services.variant_grouping import GroupingFile, GroupingParams

from .support import (
    CONTENT_PARAMS,
    Look,
    Scenario,
    by_prefix,
    group_of,
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
        assert g.groups[0].reasons["c1 parent+cohesion"] == 3

    def test_too_many_units_is_a_container(self):
        """More than ``max_units`` (8) units: a pack, not a location, unless the whole folder
        is cohesive (c0). Two themes here, so units sharing one stay apart too."""
        scenario = rooms("Maker/Castle Keep", 9)
        scenario.files = {
            p: dataclasses.replace(look, theme="other" if p < "Maker/Castle Keep/G" else "one")
            for p, look in scenario.files.items()
        }
        g = run_content(scenario)
        assert len(g.groups) == 9
        assert g.decisions["maker/castle keep"].container

    def test_cohesive_folder_over_the_cap_joins_whole(self):
        """c0 (E5 fix 0b): every unit shares production and theme, and child folders give
        the structural evidence."""
        g = run_content(rooms("Maker/Castle Keep", 9))
        assert len(g.groups) == 1 and g.groups[0].reasons["c0 whole-folder"] == 8
        assert not g.decisions["maker/castle keep"].container

    def test_generic_name_is_a_container(self):
        g = run_content(rooms("Maker/Pack 03", 3))
        assert len(g.groups) == 3
        assert g.decisions["maker/pack 03"].why == "generic name"

    def test_cohesion_gates_the_parent(self):
        """Different maps under a specific parent (a same-maker pack): no theme, no join."""
        scenario = rooms("Maker/Castle Keep", 3)
        scenario.files = {
            p: dataclasses.replace(look, theme=look.layout) for p, look in scenario.files.items()
        }
        assert len(run_content(scenario).groups) == 3

    def test_parent_needs_content(self):
        """Seal pass: the parent rule is content-gated, so it is withheld."""
        g = run_paths(rooms("Maker/Castle Keep", 4).grouping_files())
        assert len(g.groups) == 4


class TestNameRules:
    def test_same_name_joins(self):
        g = run_paths(files(["M/F/ForestRoad_Day.jpg", "M/F/Forest_Road_Night_Gridless.jpg"]))
        assert len(g.groups) == 1 and g.groups[0].reasons["a2 same-name"] == 1

    def test_levels_join_as_floors_of_one_map(self):
        g = run_paths(
            files([f"2mtt/Abandoned House - {lv} - 8x6.png" for lv in ("Floor 1", "Floor 2")])
        )
        assert len(g.groups) == 1
        assert set(g.groups[0].subgroups.values()) == {"Floor 1", "Floor 2"}

    def test_numbered_family_carries_no_name(self):
        """Audit fix 4: ``IMG_0001`` ... are a numbering, not one map."""
        g = run_paths(files([f"Camera/IMG_{k:04d}.jpg" for k in range(8)]))
        assert len(g.groups) == 8

    def test_shared_base_joins_a_small_family(self):
        g = run_paths(files([f"Flat Pack/Forest_Road_{w}.jpg" for w in ("Bridge", "Camp")]))
        assert len(g.groups) == 1 and g.groups[0].reasons["a4 shared-base"] == 1

    def test_shared_base_over_a_big_family_needs_cohesion(self):
        """A shared base over > 8 units looks like a collection (audit fix 8)."""
        words = ["bridge", "camp", "gate", "ruins", "well", "shrine", "mill", "pond", "lake"]
        paths = [f"Library/Pack/Forest Road {w.title()}/Forest_Road_{w}.jpg" for w in words]
        assert len(run_paths(files(paths)).groups) == 9

    def test_folder_named_map_joins_its_files(self):
        """a5: the folder's common tokens are the map's name, only variant words remain."""
        paths = [
            f"Moonlight Maps/Forest Switch Maps/MA 1/Grid/Moonlight_Maps_Forest_Switch_{w}_25x25.jpg"
            for w in ("Six101", "Five17", "Three05")
        ]
        g = run_paths(files(paths))
        assert len(g.groups) == 1
        assert g.decisions["moonlight maps/forest switch maps"].folder_named

    def test_unnamed_parts_join_a_named_map(self):
        """b5 (audit fix 5): ``Isolated Floors/1st_Floor.png`` inside Roadside Watchtower."""
        base = "Neutral Party/Roadside Watchtower Expert 30x26"
        paths = [f"{base}/Roadside_Watchtower{v}.jpg" for v in ("", "_Night", "_Foggy")]
        paths += [f"{base}/Isolated Floors/{k}_Floor.png" for k in ("1st", "2nd", "3rd")]
        g = run_paths(files(paths))
        assert len(g.groups) == 1
        assert g.groups[0].reasons["b5 unnamed parts"] == 1
        assert set(g.groups[0].subgroups.values()) == {"Isolated Floors"}


class TestFollowUps:
    """Deliberate deviations from E5 (design/variant-grouping.md, "Deviations from E5")."""

    def test_variant_only_files_in_a_named_folder_join_at_seal(self):
        """a6: ``Golden Forest/Night.webp`` ... is one map, as today's parser Pass 0."""
        g = run_paths(files([f"Golden Forest/{v}.webp" for v in ("Night", "Day", "Snow")]))
        assert len(g.groups) == 1
        assert g.groups[0].reasons["a6 variant-only folder"] == 2
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
        assert len(g.groups) == 1 and g.groups[0].reasons["a3 same-layout"] == 2

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
        assert not g.decisions["maker/castle keep/old library"].container


class TestContentRules:
    def test_agreement_never_joins_against_names(self):
        """Same layout, but the names carry different keys: two maps (a3 is vetoed)."""
        scenario = Scenario(
            {
                "M/Flat/Forest_Road_Day.jpg": Look("one layout"),
                "M/Flat/Desert_Camp_Day.jpg": Look("one layout", variant=1),
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
        assert len(g.groups) == 1 and g.groups[0].reasons["x1 rendition"] == 1

    def test_renditions_between_two_large_groups_are_a_suggestion(self):
        out = {}
        for maker, name in (("Kraken Maker", "Kraken Cove"), ("Dragon Maker", "Dragon Peak")):
            for k in range(20):
                slug = name.replace(" ", "_")
                out[f"{maker}/{name}/{slug}_v{k}.jpg"] = Look(name, variant=k)
        # a Kraken Cove image filed (and named) as Dragon Peak: a rendition across two big groups
        out["Dragon Maker/Dragon Peak/Dragon_Peak_v99.jpg"] = Look("Kraken Cove", rendition=1)
        g = run_content(Scenario(out))
        assert len(g.groups) == 2
        assert [s.reason for s in g.suggestions] == ["rendition(two large groups)"]

    def test_missing_features_withhold_content_joins(self):
        """A room without features takes part through names and folders only."""
        scenario = rooms("Maker/Castle Keep", 3)
        content = scenario.content()
        for path in by_prefix(content.keys(), "Maker/Castle Keep/Chapel/"):
            del content[path]
        from backend.app.services.variant_grouping import group_with_content

        from .support import parser

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
        assert group_of(g, "Maker/Castle Keep/Armory/Armory_Print.jpg").reasons["a1 rendition"] == 1

    def test_whole_folder_joins_a_cohesive_named_folder(self):
        """c0 (audit: Limithron Coral Reef): colour variants that only content can join, in a
        folder named after its files."""
        base = "limithron/Limithron Coral Reef Shipwreck Battlemap 45x45"
        out = {}
        for colour in ["Blighted", "Blue-Hole", "Tide-Pool-Ghost-Ship", "Sunken-Wreck"]:
            for grid, suffix in (("Gridded", "Grid"), ("No Grid", "NoGrid")):
                path = f"{base}/{grid}/Limithron-Coral-Reef-{colour}-45x45-{suffix}.jpg"
                out[path] = Look(f"reef {colour}", "coral reef", rendition=int(suffix == "Grid"))
        scenario = Scenario(out)
        assert len(run_paths(scenario.grouping_files()).groups) == 4
        g = run_content(scenario)
        assert len(g.groups) == 1 and g.groups[0].reasons["c0 whole-folder"] == 3

    def test_similarity_alone_never_joins(self):
        """A flat folder of cohesive one-image maps (dndavid): suggestions, no joins."""
        out = {f"dndavid/{n}HD.jpg": Look(n, "style") for n in ("Agora", "Arena", "Crypt")}
        g = run_content(Scenario(out))
        assert len(g.groups) == 3
        assert {s.reason for s in g.suggestions} == {"cohesive, no folder/name evidence"}


def test_small_maker_folder_keeps_maps_apart():
    """Follow-up 1: two maps of one maker whose files all start ``Moonlight_Maps_`` share the
    2-token key ``moonlight maps``. It is only the maker folder's name, and different
    multi-token names follow it, so it is a house prefix, not a shared base (E5 joined them)."""
    paths = [
        f"Moonlight Maps/{m}/MA/Moonlight_Maps_{m.replace(' ', '_')}_{v}_18x22.jpg"
        for m in ("Forest Cottage", "Forest Switch")
        for v in ("Grass01", "Snow02_Night")
    ]
    g = run_paths(files(paths))
    assert sorted(grp.name for grp in g.groups) == ["Forest Cottage", "Forest Switch"]
    assert {grp.author for grp in g.groups} == {"Moonlight Maps"}


def test_small_flat_maker_folder_keeps_maps_apart():
    paths = [
        f"Moonlight Maps/Moonlight_Maps_{m}_{v}_18x22.jpg"
        for m in ("Forest_Cottage", "Deep_Cave")
        for v in ("Grass01", "Snow02_Night")
    ]
    g = run_paths(files(paths))
    assert sorted(grp.name for grp in g.groups) == ["Deep Cave", "Forest Cottage"]


def test_folder_name_followed_by_variant_words_is_the_map():
    """Only variant words follow the folder's name: the folder is the map (unchanged)."""
    paths = [f"Forest Road/Forest_Road_{v}.jpg" for v in ("Day", "Night", "Snow_Night")]
    assert len(run_paths(files(paths)).groups) == 1
