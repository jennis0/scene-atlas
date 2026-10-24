"""Word lists for variant grouping (design/variant-grouping-algorithm.md §4–5).

Tokens are lower-case, as produced by ``names.tokenize``. The lists are benchmark-sensitive:
changing one changes which folders are transparent and which name tokens carry identity, so
re-run scene-atlas-learning's parity bench after editing one.
"""

from __future__ import annotations


def _words(text: str) -> frozenset[str]:
    """A word list written as whitespace-separated text."""
    return frozenset(text.split())


# Marker token for an ``NxM`` size in a name ("30x30", "12 x 12"): sizes are renditions, never
# identity, but a token in their place keeps word positions intact.
DIMS = "<nxm>"

# Words that never carry identity on their own (articles and the like).
STOPWORDS = _words("the a an of and in on at to s")

# Variant-axis words (time of day, weather, season, lighting, state, grid and format): a name made
# only of these describes a variant of a map, not a map.
AXIS = _words(
    """
grid grids gridded gridless griless nogrid ungridded unggrided gl gd hex hexgrid square squares
dpi ppi px hd uhd hq lq hi res resolution fullres fr vtt roll20 r20 foundry fvtt fgu print printable
online digital preview thumb thumbnail version ver alt alts alternate alternative variant variants var
day daytime daylight night nighttime dawn dusk sunset sunrise evening morning noon midday twilight
winter summer autumn fall spring snow snowy snowing rain rainy raining fog foggy mist misty storm
stormy blizzard cloudy overcast
light lit unlit dark darker dim bright lights lighting shadow shadows
clean dirty ruined destroyed burning burnt fire blood bloody empty furnished props prop propless
noprops isolated outline outlines line lines lineart bw original plain basic
"""
)

# Rendition words: grid, format, resolution, platform and size. A folder named only with these
# (``Gridded``, ``70 DPI (VTT)``, ``MA``) holds renditions of its parent's maps, so it is
# transparent in the effective tree. ``ma`` is a Moonlight Maps "map assets" folder.
REND = _words(
    """
grid grids gridded gridless griless nogrid ungridded unggrided gl gd hex hexgrid square squares lines
dpi ppi px hd uhd hq lq hi high low res resolution fullres full fr vtt roll20 r20 foundry fvtt fgu
owlbear dungeondraft print printable printing online digital jpg jpeg png webp file files format
formats version versions ver ma tokens token transparent preview previews thumb thumbs thumbnail
size sizes small medium large big mini web scaled cropped crop
"""
)

# Function words that only mean something next to a grid word ("no grid", "with grid"): the pair
# is dropped as one rendition phrase, while "no" elsewhere ("No Time Left") is kept.
PHRASE_HEADS = frozenset({"no", "with", "without", "non"})
GRID_WORDS = frozenset({"grid", "grids", "gridded", "lines"})

# Library words that carry no identity: "ElectrifiedBattleMaps_" must not key three maps together
# as "electrified battle". "battle maps" as a pair is handled in names.py.
NOID = frozenset({"battlemaps", "battlemap"})

# Folder names that never name a map: generic library, download and packaging words. A folder
# whose identity is only these (``Maps``, ``Pack 03``, ``New folder (2)``) is a container.
# "library" and "archive" are not generic: they name rooms ("Library", "Old Library", "Archives").
GENERIC = _words(
    """
maps map battlemaps battlemap battle battles downloads download downloaded old new folder misc
miscellaneous collection collections pack packs bundle bundles assets asset images image pictures
stuff unsorted sorted other others various extracted unzipped patreon release releases rewards
reward month monthly content set sets part volume vol all my mine
"""
)

# Camera, scan and screenshot counters (``IMG_0012``, ``DSC01234``, ``Screenshot 3``): a file
# named only by one of these and numbers has no identity, so such files never join by name,
# however few (``generic_keys`` only catches families of >= 6). Real one-word names keep theirs.
COUNTER_WORDS = _words("img dsc dscn dcim pxl photo screenshot scan untitled image")

# Series words whose number is part of a map's identity: ``Vol4`` and ``Vol6`` are different maps,
# so the number is glued on (``vol#4``). Floor and part numbers are not identity (see LEVEL).
SERIES = _words("vol volume book chapter ch episode ep season issue pt")

# Words whose following number names a floor, level or part of one map (``Floor 2`` ->
# ``floor#2``): such numbers separate layouts within a group, not groups.
LEVEL = _words(
    "floor floors level levels lvl part pt basement room area zone section tile stage deck storey "
    "story b f l"
)

# Level names without a number ("roof", "basement"): a file naming one is a part of its map.
LEVEL_WORDS = _words(
    "ground basement roof rooftop cellar attic upper lower top bottom middle interior exterior "
    "underground upstairs downstairs"
)

# Words that name a part of a map rather than a map. A file whose identity is only these
# (``1st_Floor.png``, ``Isolated Floors/…``) carries no name of its own (rule b5).
PART_WORDS = LEVEL_WORDS | _words(
    "floor floors level levels part parts room rooms piece pieces section tile tiles"
)

# Level designators trailing a file's identity ("Inn_Basement", "Inn_Floor2", "Heather House
# Upper Level"): they say which floor of a map a file is, not which map, so they are cut from the
# identity and floors of one map join by name.
# A trailing run is cut only if it holds a level noun, so "Hill Top" keeps "top". "interior" /
# "exterior" are kept: Czepeku publishes interiors as separate maps.
LEVEL_NOUNS = _words(
    "floor floors level levels lvl storey story basement cellar attic roof rooftop upstairs "
    "downstairs"
)
LEVEL_QUALIFIERS = _words("ground upper lower top bottom middle first second third fourth fifth")

# Ordinal words before "floor" / "level" ("second floor" -> floor#2). "1st" needs no entry: the
# tokenizer reads it as "1", which ``level_tag`` handles as a number.
ORDINALS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}

# Tokenizer details: ordinal suffixes are dropped after a number ("1st" -> "1"), and a
# platform name split at its digits is glued back ("Roll20" -> "roll20", "R20" -> "r20").
ORDINAL_SUFFIXES = frozenset({"st", "nd", "rd", "th"})
GLUED_PAIRS = frozenset({("roll", "20"), ("r", "20")})

# ---- Scenes

# Role words: what a picture is for, not which place it shows. Stripped from scene names like
# variant words ("TC_Anglers Wharf Night_Exterior Scene", "BellhammerMineScene", "Banner").
ROLE_WORDS = _words(
    "scene scenes art arts artwork artworks illustration illustrations illustrated banner banners "
    "cover covers promo promos promotional concept concepts conceptart handout handouts photo "
    "photos splash keyart poster posters image images picture pictures render renders"
)
# Words that may make up a role folder's name besides role words ("Assets & Tokens", "Bonus").
ROLE_FOLDER_EXTRA = _words("assets asset tokens token extras extra bonus misc")
# A folder that only says it holds maps ("Maps", "Battle Maps", "Battlemaps").
MAPS_FOLDER_WORDS = _words("maps map battlemaps battlemap battle")
# Scene variant words the map vocabulary lacks.
SCENE_AXIS = _words("default")
