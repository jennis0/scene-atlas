"""Scenarios built from real folders of the E5 audit (scene-atlas-learning
``results/grouping/e5-audit.md``), with synthetic content features (``support.Look``).

Each builder returns a ``Scenario``; the tests in ``test_scenarios.py`` state what the walk must
do with it, with and without content.
"""

from __future__ import annotations

from .support import Look, Scenario

ROOMS = ["Beast Prison", "Cross Platform", "Garden", "Research Chamber", "Teleport Chamber"]


def _slug(name: str) -> str:
    return name.replace(" ", "_")


def _moonlight_room(base: str, room: str, folder: str, theme: str) -> dict[str, Look]:
    """One Moonlight Maps room as packaged: ``<room 12x12>/MA/{Grid,No Grid}`` and ``VTT``."""
    s = _slug(room)
    files: dict[str, Look] = {}
    for v, variant in enumerate(["var01", "var02_Night"]):
        look = Look(room, theme, variant=v)
        files[
            f"{base}/{folder}/{room} 12x12/MA/Grid/Moonlight_Maps_{s}_{variant}_12x12_grid.jpg"
        ] = Look(room, theme, variant=v, rendition=1)
        files[f"{base}/{folder}/{room} 12x12/MA/No Grid/Moonlight_Maps_{s}_{variant}_12x12.jpg"] = (
            look
        )
        tag = room.split()[-1].lower()
        files[f"{base}/{folder}/VTT/Moonlight_Maps_{s}_{tag}0{v + 3}_12x12_72_[tower].jpg"] = Look(
            room, theme, variant=v, rendition=2
        )
    return files


def wizard_tower() -> Scenario:
    """Moonlight Maps' Never Ending Wizard Tower (audit, recipe ``nest`` / ``orig``): five room
    folders, each wrapping rendition folders (``Beast Prison 12x12``, ``MA/Grid``, ``VTT``). The
    room folder for the teleport chamber is called ``Teleport Room``. The maker folder also holds
    ten unrelated maps, so it is a container."""
    files: dict[str, Look] = {}
    tower = "Moonlight Maps/Never Ending Wizard Tower"
    for room in ROOMS:
        folder = "Teleport Room" if room == "Teleport Chamber" else room
        files |= _moonlight_room(tower, room, folder, theme="wizard tower")
    for k, other in enumerate(
        ["Forest Road", "Deep Cave", "City Street", "Cliff Pass", "Fey River", "Heather House"]
        + ["King of the Hill", "Temple Sanctuary", "Graveyard Mausoleum", "Archery Tournament"]
    ):
        s = _slug(other)
        for v, variant in enumerate(["Grass01", "Snow02_Night"]):
            for grid, r in (("_grid", 1), ("", 0)):
                path = f"Moonlight Maps/{other}/MA/Moonlight_Maps_{s}_{variant}_18x22{grid}.jpg"
                files[path] = Look(other, variant=v, rendition=r, aspect=1.0 + 0.1 * k)
    return Scenario(files)


def leasealair() -> Scenario:
    """leasealair (audit, new maker): one flat folder, every file carrying the collection prefix
    ``leasealairMaps_LeasealairMaps_`` and the original maker, three renditions per map, plus
    ``NumberedGLMaps_N`` twins that are renditions of a named file."""
    files: dict[str, Look] = {}
    maps = [
        ("TomCartos", "CrystalCaves"),
        ("TomCartos", "TheMaze"),
        ("TomCartos", "Banquet"),
        ("SeafootGames", "TheSoulWell"),
        ("SeafootGames", "TheGreatCogs"),
        ("FantasyAtlas", "IntoTheAir"),
        ("FantasyAtlas", "DungeonWithDragonSkulls"),
        ("TehoxMaps", "TehoxmapsThemagmachamber"),
        ("ForgottenAdventures", "ForgottenadventuresWitheredTree"),
        ("DomilleMisjayMaps", "DomilleMisjayMeetingOfWater"),
        ("SirinkmanImaginebetterworlds", "SirinkmanDeepwater"),
        ("SirinkmanImaginebetterworlds", "SirinkmanFirehall"),
    ]
    for k, (maker, name) in enumerate(maps):
        layout = f"{maker}/{name}"
        for r, suffix in enumerate(["Grid", "Gridless", "Print"]):
            path = f"leasealair/leasealairMaps_LeasealairMaps_{maker}_{name}{suffix}.jpg"
            files[path] = Look(layout, rendition=r, aspect=1.0 + 0.05 * k)
        files[f"leasealair/NumberedGLMaps_{50 + k}.jpg"] = Look(
            layout, rendition=3, aspect=1.0 + 0.05 * k
        )
    return Scenario(files)


DNDAVID = [
    "AbandonedTempleHD",
    "AgoraHD",
    "TheArenaHD",
    "HealingPoolsHD",
    "forest_ruins_temple",
    "frozen_ice_temple",
    "mountain_forge_temple",
    "volcano_mountain_temple",
    "ArborWatchTower HD",
    "ocean_temple_cliffes",
    "CoastalTempleHD",
    "DesertOasisHD",
    "DwarvenForgeHD",
    "ElvenSanctumHD",
    "GoblinWarrenHD",
    "HauntedCryptHD",
    "JungleShrineHD",
    "LavaBridgeHD",
    "MoonlitGladeHD",
    "PirateCoveHD",
    "SkyCitadelHD",
    "SwampHutHD",
]


def dndavid() -> Scenario:
    """dndavid (audit, new maker): 22 one-image maps in one flat folder. Every map is drawn in
    one style, so they are all cohesive: similarity alone must still never join them."""
    return Scenario({f"dndavid/{name}.jpg": Look(name, theme="dndavid style") for name in DNDAVID})


PACK = ["General Store", "Graveyard", "King of the Hill", "Deep Cave", "City Street", "Cliff Pass"]


def moonlight_pack() -> Scenario:
    """Moonlight Maps ``Pack 02`` (audit, recipe ``pack``): different maps flat in a generic
    folder, two of them in one theme; and a ``Forest Adventures`` pack (a specific parent) of
    three different maps in their own folders."""
    files: dict[str, Look] = {}
    for k, name in enumerate(PACK):
        s = _slug(name)
        theme = "shared town theme" if k < 2 else None
        for v, variant in enumerate(["Day01", "Night02"]):
            for grid, r in (("_grid", 1), ("", 0)):
                files[f"Moonlight Maps/Pack 02/Moonlight_Maps_{s}_{variant}_25x30{grid}.jpg"] = (
                    Look(name, theme, variant=v, rendition=r, aspect=1.2)
                )
    for name in ["Hidden Camp", "Witch Hut", "Old Bridge"]:
        s = _slug(name)
        for v, variant in enumerate(["Day", "Night"]):
            files[f"Forest Adventures/{name}/{s}_{variant}.jpg"] = Look(name, variant=v, aspect=1.2)
    return Scenario(files)


MOONLIGHT_FOREST = ["Forest Road", "Archery Tournament", "Fey River", "Coastal Forest"]
MOONLIGHT_FOREST += ["Hunters Ravine", "Witch Lair", "Druid Circle"]
# Moonlight variant names carry words of their own ("Candy_Cane02"), so each map has several
# distinct names: that is what marks ``moonlight maps`` as a house hub (``names.find_hubs``).
MOONLIGHT_VARIANTS = ["Grass01", "Candy_Cane02_Night", "Pumpkin03", "Ruins04_Snow"]
OTHER_FOREST = {
    "SecludedTeaValley": ["fog", "rain"],
    "MysteriousDruidGrove": ["dark", "day"],
    "Abandoned_Campsite": ["", "_Eerie"],
    "Forest_Ruins": ["_Day", "_Night"],
    "Hidden_Glade": ["_Summer", "_Winter"],
    "Elven_Outpost": ["_Day", "_Night"],
}


def topic_folder() -> Scenario:
    """A topic folder holding several makers' maps flat (audit, recipe ``topic``), and
    topic / author / group folders where the author folder recurs under several topics
    (``topic_author_group``: ``Woods/Moonlight Maps`` must not merge its maps). Every map of
    one maker in a topic shares a style, so cohesion alone would join them; the other makers'
    maps share another style (one maker draws ``Forest Road``, another ``Forest Ruins``)."""
    files: dict[str, Look] = {}
    for name in MOONLIGHT_FOREST:
        s = _slug(name)
        for v, variant in enumerate(MOONLIGHT_VARIANTS):
            files[f"Forests/Moonlight_Maps_{s}_{variant}_18x22.jpg"] = Look(name, "forest", v)
    for stem, variants in OTHER_FOREST.items():
        for v, variant in enumerate(variants):
            sep = "_" if variant and not variant.startswith("_") else ""
            files[f"Forests/{stem}{sep}{variant}.jpg"] = Look(stem, "forest, other makers", v)
    topics = {"Woods": ["Forest Switch", "Forest Temple", "Druid Grove"], "Caves": ["Deep Cave"]}
    topics["Caves"] += ["Crystal Cavern", "Goblin Den"]
    for topic, maps in topics.items():
        for name in maps:
            s = _slug(name)
            for v, variant in enumerate(["Grass01", "Snow02_Night"]):
                path = f"{topic}/Moonlight Maps/{name}/MA/Moonlight_Maps_{s}_{variant}_18x22.jpg"
                files[path] = Look(name, theme=topic, variant=v)
    return Scenario(files)


FLOORS = ["floor-01", "floor-02", "floor-03", "floor-04", "floor-05"]
CASTLE_VARIANTS = ["dark-night", "empty-day", "no-background-day"]


def czepeku() -> Scenario:
    """Czepeku (audit): ``japanese-castle-interior`` (files ``JapaneseCastleInterior_<floor>-<
    variant>``: five floors) and a flat maker folder of ``<Map>_<variant>`` files whose suffixes
    are variant words only."""
    files: dict[str, Look] = {}
    for floor in FLOORS:
        for v, variant in enumerate(CASTLE_VARIANTS):
            path = f"Czepeku/japanese-castle-interior/JapaneseCastleInterior_{floor}-{variant}.webp"
            files[path] = Look(f"castle {floor}", theme="japanese castle", variant=v)
    for name in ["SecludedTeaValley", "YggdrasilRoots", "OrbitalLift", "IslandFort"]:
        for v, variant in enumerate(["day", "night", "fog", "winter"]):
            files[f"Czepeku Flat/{name}_{variant}.webp"] = Look(name, variant=v)
    return Scenario(files)


def mirror_folders() -> Scenario:
    """Gridded / gridless mirror folders: sibling folders named ``X Gridded`` / ``X Gridless``,
    and the whole library split by grid at the top (``Gridded/X``, ``Gridless/X``)."""
    files: dict[str, Look] = {}
    for grid, r in (("Gridded", 1), ("Gridless", 0)):
        for v, variant in enumerate(["Day", "Night"]):
            files[f"Maker/Forest Road {grid}/ForestRoad_{variant}.jpg"] = Look(
                "forest road", variant=v, rendition=r
            )
            files[f"{grid}/Swamp Hut/SwampHut_{variant}.jpg"] = Look(
                "swamp hut", variant=v, rendition=r
            )
    return Scenario(files)


SCENARIOS = {
    "wizard_tower": wizard_tower,
    "leasealair": leasealair,
    "dndavid": dndavid,
    "moonlight_pack": moonlight_pack,
    "topic_folder": topic_folder,
    "czepeku": czepeku,
    "mirror_folders": mirror_folders,
}
