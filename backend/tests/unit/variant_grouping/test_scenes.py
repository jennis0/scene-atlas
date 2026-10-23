"""Scenes in an import's grouping (variant_grouping.scenes, research E7), through the public API."""

import dataclasses

from backend.app.services.variant_grouping import (
    GroupingFile,
    SceneGrouping,
    group_scenes,
    group_with_content,
)

from .support import CONTENT_PARAMS, Look, features, parser

MAP, SCENE = "map", "scene"


def run(files: dict[str, tuple[str, Look]], params=CONTENT_PARAMS):
    """(map grouping, scene grouping) of an import: path -> (type, what it depicts)."""
    maps = [GroupingFile(p, p) for p, (kind, _) in files.items() if kind == MAP]
    scenes = [GroupingFile(p, p) for p, (kind, _) in files.items() if kind == SCENE]
    content = {p: features(look) for p, (_, look) in files.items()}
    grouping = group_with_content(maps, content, params, parser()) if maps else None
    return grouping, group_scenes(grouping, maps, scenes, content, params)


def attached_to(grouping, scenes: SceneGrouping, path: str) -> str | None:
    """The first map key of the group ``path`` is attached to, or None."""
    attachment = scenes.attachments.get(path)
    return None if attachment is None else grouping.groups[attachment.group].keys[0]


def partition(scenes: SceneGrouping) -> set[frozenset[str]]:
    return {frozenset(g) for g in scenes.groups}


def keep_maps(base: str = "Maker/Keep") -> dict[str, tuple[str, Look]]:
    return {
        f"{base}/Keep_{v}.jpg": (MAP, Look("keep", "keep", k))
        for k, v in enumerate(["Day", "Night"])
    }


class TestAttachByFolder:
    def test_a_scene_in_its_maps_folder_joins_them(self):
        files = keep_maps()
        files["Maker/Keep/Keep Scene.jpg"] = (SCENE, Look("keep vista"))
        files["Maker/Keep/Scenes/Vista.jpg"] = (SCENE, Look("vista 2"))
        files["Maker/Keep/Assets & Tokens/Art.jpg"] = (SCENE, Look("vista 3"))
        grouping, scenes = run(files)
        for path in ("Maker/Keep/Keep Scene.jpg", "Maker/Keep/Scenes/Vista.jpg"):
            assert attached_to(grouping, scenes, path) == "Maker/Keep/Keep_Day.jpg"
        assert attached_to(grouping, scenes, "Maker/Keep/Assets & Tokens/Art.jpg") is not None

    def test_one_map_and_its_scenes_in_one_folder_are_one_group(self):
        files = {"Map.jpg": (MAP, Look("map"))}
        files |= {f"Scene {k}.jpg": (SCENE, Look(f"scene {k}")) for k in range(5)}
        _, scenes = run(files)
        assert len(scenes.attachments) == 5 and not scenes.groups

    def test_not_through_the_import_root(self):
        files = {"Map.jpg": (MAP, Look("map")), "Random Scenes/x.jpg": (SCENE, Look("x"))}
        _, scenes = run(files)
        assert not scenes.attachments and partition(scenes) == {frozenset({"Random Scenes/x.jpg"})}

    def test_not_from_beside_a_location(self):
        """``Session 12`` holds one location, but it is not the location's folder."""
        files = keep_maps("Session 12/Forest Cabin")
        files["Session 12/Forest/x.jpg"] = (SCENE, Look("x"))
        files["Session 12/y.jpg"] = (SCENE, Look("y"))
        _, scenes = run(files)
        assert not scenes.attachments

    def test_a_locations_extra_folder_joins_it(self):
        """The location's own top folder holds the scene's folder (``Bonus Content``)."""
        files = {
            f"Loc/{floor}/{floor.replace(' ', '_')}_{v}.jpg": (MAP, Look(floor, "loc", k))
            for floor in ("Floor 1", "Floor 2")
            for k, v in enumerate(["Day", "Night"])
        }
        files["Loc/Bonus Content/x.jpg"] = (SCENE, Look("x"))
        grouping, scenes = run(files)
        assert len(grouping.groups) == 1
        assert attached_to(grouping, scenes, "Loc/Bonus Content/x.jpg") is not None

    def test_mirrored_maps_and_scenes_folders(self):
        files = {
            f"Pack/maps/beachside-bazaar/{v}.webp": (MAP, Look("bazaar", variant=k))
            for k, v in enumerate(["rain", "day"])
        }
        files |= {
            f"Pack/maps/canal-city/{v}.webp": (MAP, Look("canal", variant=k))
            for k, v in enumerate(["rain", "day"])
        }
        files["Pack/scenes/beachside-bazaar/sunset.webp"] = (SCENE, Look("bazaar view"))
        grouping, scenes = run(files)
        attached = attached_to(grouping, scenes, "Pack/scenes/beachside-bazaar/sunset.webp")
        assert attached is not None and "beachside-bazaar" in attached


class TestAttachByName:
    @staticmethod
    def wharf_and_mine() -> dict[str, tuple[str, Look]]:
        files = {
            f"TC/TC_Anglers Wharf_{g}.jpg": (MAP, Look("wharf", rendition=k))
            for k, g in enumerate(["No Grid", "Grid"])
        }
        files |= {
            f"TC/TC_Bellhammer Mine_{g}.jpg": (MAP, Look("mine", rendition=k))
            for k, g in enumerate(["No Grid", "Grid"])
        }
        return files

    def test_a_scene_named_after_one_map_joins_it(self):
        files = self.wharf_and_mine()
        files["TC/TC_Anglers Wharf Night_Exterior Scene.jpg"] = (SCENE, Look("wharf scene"))
        files["TC/BellhammerMineScene_JamesRPGArt.jpg"] = (SCENE, Look("mine scene"))
        grouping, scenes = run(files)
        wharf = attached_to(grouping, scenes, "TC/TC_Anglers Wharf Night_Exterior Scene.jpg")
        mine = attached_to(grouping, scenes, "TC/BellhammerMineScene_JamesRPGArt.jpg")
        assert wharf is not None and "Anglers" in wharf
        assert mine is not None and "Bellhammer" in mine

    def test_only_neighbours(self):
        """A scene in a topic folder never joins a map elsewhere by name."""
        files = {
            f"Czepeku/Desert Ruins/DesertRuins_{v}.jpg": (MAP, Look("ruins", variant=k))
            for k, v in enumerate(["Day", "Night"])
        }
        files |= {
            f"Czepeku/Desert Camp/DesertCamp_{v}.jpg": (MAP, Look("camp", variant=k))
            for k, v in enumerate(["Day", "Night"])
        }
        files["Scenes/Forest/desert-ruins_Default.jpg"] = (SCENE, Look("ruins scene"))
        _, scenes = run(files)
        assert not scenes.attachments


class TestRenditionOfAMap:
    def test_a_copy_of_a_map_joins_it_anywhere(self):
        files = keep_maps()
        files |= {
            f"Maker/Fort/Fort_{v}.jpg": (MAP, Look("fort", variant=k))
            for k, v in enumerate(["Day", "Night"])
        }
        files["Elsewhere/Downloads/keep copy.jpg"] = (SCENE, Look("keep", "keep", rendition=1))
        grouping, scenes = run(files)
        attachment = scenes.attachments["Elsewhere/Downloads/keep copy.jpg"]
        assert attachment.reason == "r7 rendition of a map"
        assert grouping.groups[attachment.group].keys[0] == "Maker/Keep/Keep_Day.jpg"


class TestSceneGroups:
    def test_scenes_start_alone(self):
        """Distinct names in one folder (``Art/Scenes``): no shared word joins them."""
        names = [
            "forest_cathedral",
            "forest_cathedral_entrance",
            "forest_shallow_river",
            "foggy_dark_village",
            "ruined_village",
        ]
        _, scenes = run({f"Art/Scenes/{n}.jpg": (SCENE, Look(n, "art")) for n in names})
        assert len(scenes.groups) == 5

    def test_numbers_and_ids_are_not_names(self):
        stems = ["the-art-of-x-07", "the-art-of-x-08", "the-digital-art-of-x-16"]
        stems += ["582d0779-7cee-4044-8a3e-1f2b3c4d5e6f", "8765314b-e834-4a1b-9c2d-0e1f2a3b4c5d"]
        stems += ["d83lgl", "3lgl8v"] + [f"{k:04d}" for k in range(1, 5)]
        _, scenes = run({f"Wallpapers/{s}.jpg": (SCENE, Look(s)) for s in stems})
        assert len(scenes.groups) == len(stems)

    def test_copies_by_name_alone_are_not_variants(self):
        """``x`` and ``x (2)`` with different pictures: identical stems are no name evidence."""
        _, scenes = run({"Art/x.jpg": (SCENE, Look("a")), "Art/x (2).jpg": (SCENE, Look("b"))})
        assert len(scenes.groups) == 2

    def test_one_name_with_variant_words_is_one_scene(self):
        files = {
            "Art/Tavern Day.jpg": (SCENE, Look("a")),
            "Art/Tavern Night.jpg": (SCENE, Look("b")),
        }
        _, scenes = run(files)
        assert partition(scenes) == {frozenset(files)}

    def test_a_place_folder_of_variant_names_is_one_scene(self):
        files = {
            "Golden Forest/Day.jpg": (SCENE, Look("a")),
            "Golden Forest/Night.jpg": (SCENE, Look("b")),
        }
        _, scenes = run(files)
        assert partition(scenes) == {frozenset(files)}

    def test_agreeing_content_joins(self):
        """A Day / Night repaint of one view (same layout, close embedding), named apart."""
        files = {
            "Art/0.jpg": (SCENE, Look("swamp")),
            "Art/3.jpg": (SCENE, Look("swamp", variant=1)),
        }
        _, scenes = run(files)
        assert partition(scenes) == {frozenset(files)}
        no_embeddings = dataclasses.replace(CONTENT_PARAMS, embedding=None)
        assert len(run(files, no_embeddings)[1].groups) == 2

    def test_across_folders_only_copies_join(self):
        files = {
            "Art/With Text/castle.jpg": (SCENE, Look("castle")),
            "Art/No Text/castle-clean.jpg": (SCENE, Look("castle", rendition=1)),
            "Downloads/tower.jpg": (SCENE, Look("tower")),
            "Favourites/tower-night.jpg": (SCENE, Look("tower", variant=1)),
        }
        _, scenes = run(files)
        assert frozenset({"Art/With Text/castle.jpg", "Art/No Text/castle-clean.jpg"}) in partition(
            scenes
        )
        assert frozenset({"Downloads/tower.jpg"}) in partition(scenes)


class TestInvariance:
    def test_a_scene_never_bridges_two_map_groups(self):
        """A copy of two different maps (two map groups' renditions) joins neither."""
        files = keep_maps()
        files |= {
            f"Maker/Fort/Fort_{v}.jpg": (MAP, Look("fort", variant=k))
            for k, v in enumerate(["Day", "Night"])
        }
        files["Elsewhere/keep.jpg"] = (SCENE, Look("keep", "keep", rendition=1))
        files["Elsewhere/fort.jpg"] = (SCENE, Look("fort", rendition=1))
        grouping, scenes = run(files)
        groups = {scenes.attachments[p].group for p in ("Elsewhere/keep.jpg", "Elsewhere/fort.jpg")}
        assert len(groups) == 2 and len(grouping.groups) == 2

    def test_scenes_never_change_the_map_groups(self):
        files = keep_maps() | {"Maker/Keep/Keep Scene.jpg": (SCENE, Look("keep", "keep", 1))}
        with_scenes, _ = run(files)
        without, _ = run({p: v for p, v in files.items() if v[0] == MAP})
        assert [g.keys for g in with_scenes.groups] == [g.keys for g in without.groups]

    def test_no_maps(self):
        _, scenes = run({"Art/a.jpg": (SCENE, Look("a"))})
        assert not scenes.attachments and partition(scenes) == {frozenset({"Art/a.jpg"})}
