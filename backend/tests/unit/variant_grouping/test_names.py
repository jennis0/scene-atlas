"""Unit tests for variant_grouping.names: tokens, identity, folder IDF, hubs, levels."""

import pytest

from backend.app.services.variant_grouping import names as N
from backend.app.services.variant_grouping.names import FolderClass
from backend.app.services.variant_grouping.vocab import DIMS


class TestTokenize:
    @pytest.mark.parametrize(
        ("text", "tokens"),
        [
            ("ForestRoad_Night", ["forest", "road", "night"]),
            ("HDMapPack", ["hd", "map", "pack"]),
            ("Moonlight_Maps_Beast_Prison_var01_12x12_grid", ["moonlight", "maps", "beast", "prison", "var", "01", DIMS, "grid"]),
            ("Spell Scroll Store (8x6)", ["spell", "scroll", "store", DIMS]),
            ("Graveyard_[graveyard,cemetery]", ["graveyard"]),
            ("1st_Floor", ["1", "floor"]),
            ("Tavern Roll20 R20", ["tavern", "roll20", "r20"]),
            ("JapaneseCastleInterior_floor-01-dark-night", ["japanese", "castle", "interior", "floor", "01", "dark", "night"]),
            ("Café", ["caf"]),  # non-ASCII letters separate tokens, as in the research tokenizer
        ],
    )  # fmt: skip
    def test_tokens(self, text, tokens):
        assert N.tokenize(text) == tokens

    @pytest.mark.parametrize(
        ("text", "tokens"),
        [
            ("SirinkmanFirehall01Ungriddedvtt", ["sirinkman", "firehall", "01", "ungridded", "vtt"]),
            ("Lighthouse_Printgrid", ["lighthouse", "print", "grid"]),
            ("TheMagmaChamberVTTgrid", ["the", "magma", "chamber", "vtt", "grid"]),
            ("Firelight_Tavern", ["firelight", "tavern"]),  # no rendition word: a map name
            ("Darkfire", ["darkfire"]),
        ],
    )  # fmt: skip
    def test_glued_rendition_suffixes_split_in_file_stems(self, text, tokens):
        assert N.tokenize(text, split_glued=True) == tokens

    def test_glued_spans_cover_the_text(self):
        text = "TheMagmaChamberVTTgrid"
        spans = N.tokenize_spans(text, split_glued=True)
        assert [text[t.start : t.end] for t in spans][-2:] == ["VTT", "grid"]

    def test_spans_point_into_the_text(self):
        text = "Docks of the Dead - Tropical"
        spans = N.tokenize_spans(text)
        assert [text[t.start : t.end] for t in spans] == ["Docks", "of", "the", "Dead", "Tropical"]

    def test_ordinal_and_glued_spans_cover_both_parts(self):
        text = "2nd_Floor_Roll20"
        spans = N.tokenize_spans(text)
        assert [(t.text, text[t.start : t.end]) for t in spans] == [
            ("2", "2nd"),
            ("floor", "Floor"),
            ("roll20", "Roll20"),
        ]

    def test_file_stem_drops_extension_and_copy_suffix(self):
        assert N.file_stem("Forest Road (2).jpg") == "Forest Road"
        assert N.file_stem("no_extension") == "no_extension"

    def test_split_path(self):
        assert N.split_path("a/b/c.jpg") == (("a", "b"), "c.jpg")
        assert N.split_path("c.jpg") == ((), "c.jpg")

    def test_nxm_is_sorted(self):
        assert N.nxm_of("Map_30x20_grid") == (20, 30)
        assert N.nxm_of("Map 12 x 18") == (12, 18)
        assert N.nxm_of("Map_2025") is None


class TestIdentity:
    def ident(self, text: str) -> tuple[str, ...]:
        return N.identity_tokens(N.tokenize(text))

    def test_variant_rendition_and_numbers_are_dropped(self):
        assert self.ident("Forest_Road_Snow_Night_02_25x25_Gridless") == ("forest", "road")

    def test_stopwords_and_one_letter_tokens_are_dropped(self):
        assert self.ident("Docks of the Dead - A") == ("docks", "dead")

    def test_grid_phrase_is_dropped_but_no_elsewhere_is_kept(self):
        assert self.ident("Cellar_No_Grid") == ("cellar",)
        assert self.ident("No_Time_Left") == ("no", "time", "left")

    def test_battle_maps_carry_no_identity(self):
        """Audit fix 7: ``ElectrifiedBattleMaps_`` must not key maps as "electrified battle"."""
        assert self.ident("ElectrifiedBattleMaps_Arena") == ("electrified", "arena")
        assert self.ident("Desert_Battlemap") == ("desert",)

    def test_series_number_is_identity(self):
        assert self.ident("Dungeon_Vol4_Night") == ("dungeon", "vol#4")
        assert N.series_of(("dungeon", "vol#4")) == frozenset({"vol#4"})

    def test_repeats_are_kept_once(self):
        assert self.ident("leasealairMaps_LeasealairMaps_Oasis") == ("leasealair", "maps", "oasis")


class TestGenericWords:
    def test_rooms_are_not_generic(self):
        """Follow-up 3: "Library" and "Archives" name rooms."""
        for name in ("Library", "Old Library", "Archives"):
            assert N.folder_class(name, set())[0] is FolderClass.SPECIFIC
        assert N.folder_class("Old Downloads", set())[0] is FolderClass.GENERIC


class TestFolderClass:
    @pytest.mark.parametrize(
        ("name", "parent", "expected"),
        [
            ("Gridded", "Forest Road", FolderClass.RENDITION),
            ("70 DPI (VTT)", "Forest Road", FolderClass.RENDITION),
            ("MA", "Garden", FolderClass.RENDITION),
            ("Beast Prison 12x12", "Beast Prison", FolderClass.RENDITION),
            ("Night", "Forest Road", FolderClass.VARIANT),
            ("Gridded Winter", "Forest Road", FolderClass.VARIANT),
            ("Pack 03", "Moonlight Maps", FolderClass.GENERIC),
            ("New folder (2)", "Downloads", FolderClass.GENERIC),
            ("Teleport Chamber 12x12", "Teleport Room", FolderClass.SPECIFIC),
            ("Forest Road", "Moonlight Maps", FolderClass.SPECIFIC),
        ],
    )
    def test_classes(self, name, parent, expected):
        parent_tokens = set(N.identity_tokens(N.tokenize(parent)))
        assert N.folder_class(name, parent_tokens)[0] is expected


class TestFolderIdf:
    """Folder IDF: common tokens are a house prefix (strip) or the map's name (keep)."""

    def test_house_prefix_is_stripped(self):
        seqs = [
            ("leasealair", "maps", "crystal", "caves"),
            ("leasealair", "maps", "soul", "well"),
            ("leasealair", "maps", "great", "cogs"),
            ("leasealair", "maps", "into", "air"),
        ]
        new, info = N.folder_names(seqs)
        assert info.house and not info.named_map
        assert set(info.common) == {"leasealair", "maps"}
        assert new[0] == ("crystal", "caves")

    def test_map_name_is_kept(self):
        """Only variant-like one-word residuals remain: the common tokens name the map."""
        seqs = [("forest", "switch", "six"), ("forest", "switch", "five"), ("forest", "switch")]
        new, info = N.folder_names(seqs)
        assert info.named_map and not info.house
        assert info.common == ("forest", "switch")
        assert new == seqs

    def test_empty_residuals_count_against_house(self):
        """Audit fix 3: two floor names in a one-map folder are not a bundle."""
        seqs = [
            ("dilapidated", "building"),
            ("dilapidated", "building"),
            ("dilapidated", "building", "floor"),
            ("dilapidated", "building", "basement"),
        ]
        _, info = N.folder_names(seqs)
        assert not info.house and info.named_map

    def test_small_folders_are_not_judged(self):
        _, info = N.folder_names([("a", "b"), ("a", "b")])
        assert info.common == () and not info.house


class TestGlobalStrip:
    def test_collection_prefix_is_stripped(self):
        seqs = [("myvault", "maps", f"place{k}", f"name{k}") for k in range(25)]
        new, removed, _ = N.global_strip(seqs, [("f",)] * 25)
        assert removed == {"myvault", "maps"}
        assert new[0] == ("place0", "name0")

    def test_prefix_before_single_words_is_kept(self):
        """Residuals of one word are variants, not names: the prefix may be the map's name."""
        seqs = [("myvault", "maps", f"variant{k}") for k in range(25)]
        _, removed, _ = N.global_strip(seqs, [("f",)] * 25)
        assert removed == set()

    def test_single_map_keeps_its_name(self):
        """Audit fix 1: a single imported map has its name in every file."""
        seqs = [("young", "adventurers", "hideout", f"v{k}") for k in range(25)]
        new, removed, _ = N.global_strip(seqs, [("f",)] * 25)
        assert removed == set()
        assert new == seqs

    def test_hub_must_span_folders(self):
        """A house hub precedes many maps across folders; one multi-part map lives in one."""
        seqs, folders = [], []
        for m in range(6):
            for v in range(4):
                seqs.append(("moonlight", "maps", f"map{m}", f"part{v}"))
                folders.append((f"folder{m % 3}",))
        # other makers' files, so the hub is not in 80% of files (a collection prefix)
        seqs += [(f"other{k}", "place") for k in range(10)]
        folders += [("elsewhere",)] * 10
        _, _, hubs = N.global_strip(seqs, folders)
        assert ("moonlight", "maps") in hubs
        _, _, hubs = N.global_strip(seqs, [("one",)] * 24 + folders[24:])
        assert hubs == set()


class TestHubs:
    def test_find_hubs_needs_heavy_continuations(self):
        heavy = [("house", "maps", f"m{m}", f"v{v}") for m in range(6) for v in range(4)]
        assert ("house", "maps") in N.find_hubs(heavy)
        light = [("house", "maps", f"m{m}", f"v{v}") for m in range(6) for v in range(3)]
        assert N.find_hubs(light) == set()

    def test_strip_hub_never_strips_whole_name(self):
        hubs = {("moonlight", "maps")}
        assert N.strip_hub(("moonlight", "maps", "forest"), hubs) == ("forest",)
        assert N.strip_hub(("moonlight", "maps"), hubs) == ("moonlight", "maps")

    def test_lead_hubs(self):
        seqs = [("czepeku", f"map{m}", "x") for m in range(6) for _ in range(2)]
        assert N.lead_hubs(seqs, cover=0.4, fanout=6) == {("czepeku",)}
        assert N.lead_hubs(seqs, cover=0.4, fanout=7) == set()


class TestGenericKeys:
    def test_numbered_family_is_generic(self):
        stems = [f"NumberedGLMaps_{k}" for k in range(50, 58)]
        keys = [("numbered", "maps")] * len(stems)
        assert N.generic_keys(keys, stems) == {("numbered", "maps")}

    def test_small_family_is_not_generic(self):
        stems = [f"IMG_{k:04d}" for k in range(5)]
        assert N.generic_keys([("img",)] * 5, stems) == set()

    def test_named_variants_are_not_generic(self):
        stems = [f"Forest_Road_{w}" for w in ["Day", "Night", "Snow", "Rain", "Fog", "Dusk"]]
        assert N.generic_keys([("forest", "road")] * 6, stems) == set()


class TestLevelSuffix:
    @pytest.mark.parametrize(
        ("identity", "expected"),
        [
            (("inn", "basement"), ("inn",)),
            (("inn", "floor"), ("inn",)),
            (("heather", "house", "upper", "level"), ("heather", "house")),
            (("hill", "top"), ("hill", "top")),  # no level noun in the run
            (("sea", "level", "cave"), ("sea", "level", "cave")),  # not trailing
            (("castle", "interior"), ("castle", "interior")),  # interiors are separate maps
            (("floor",), ()),
        ],
    )
    def test_strip_level_suffix(self, identity, expected):
        assert N.strip_level_suffix(identity) == expected


class TestFolderNameKeys:
    """Follow-up 1: a 2-token key that is only an enclosing folder's name."""

    def evidence(self, paths: list[str]) -> N.NameEvidence:
        folders = [tuple(p.split("/")[:-1]) for p in paths]
        eff = [tuple(N.name_identity(c) and " ".join(N.name_tokens(c)) for c in f) for f in folders]
        stems = [N.file_stem(p.split("/")[-1]) for p in paths]
        return N.analyse_names([N.tokenize(s) for s in stems], stems, eff)

    def test_prefix_before_several_maps_is_stripped(self):
        ev = self.evidence(
            [f"Moonlight Maps/Moonlight_Maps_{m}_{v}.jpg" for m in ("Forest_Cottage", "Deep_Cave")
             for v in ("Grass", "Snow")]
        )  # fmt: skip
        assert ev.key2 == [("forest", "cottage")] * 2 + [("deep", "cave")] * 2
        assert ev.stripped[0] == frozenset({"moonlight", "maps"})

    def test_prefix_before_variant_words_is_kept(self):
        ev = self.evidence([f"Forest Road/Forest_Road_{v}.jpg" for v in ("Bridge", "Camp")])
        assert ev.key2 == [("forest", "road")] * 2

    def test_key_not_in_a_folder_name_is_kept(self):
        """Two files are too few for folder IDF, and ``Pack`` is not ``moonlight maps``."""
        ev = self.evidence(
            ["Pack/Moonlight_Maps_Forest_Cottage.jpg", "Pack/Moonlight_Maps_Deep_Cave.jpg"]
        )
        assert ev.key2 == [("moonlight", "maps")] * 2

    def test_two_files_under_the_maker_folder_are_stripped(self):
        ev = self.evidence(
            [
                "Moonlight Maps/Moonlight_Maps_Forest_Cottage.jpg",
                "Moonlight Maps/Moonlight_Maps_Deep_Cave.jpg",
            ]
        )
        assert ev.key2 == [("forest", "cottage"), ("deep", "cave")]


class TestLevels:
    @pytest.mark.parametrize(
        ("stem", "tag"),
        [
            ("Tower_Floor_2_Night", "floor#2"),
            ("JapaneseCastleInterior_floor-03-day", "floor#3"),
            ("Inn_Second_Floor", "floor#2"),
            ("Inn_1st_Floor", "floor#1"),
            ("Swamp_Manor_Roof", "roof"),
            ("Heather_House_Basement_Lit", "basement"),
            ("Forest_Road_Night", None),
        ],
    )
    def test_level_tag(self, stem, tag):
        assert N.level_tag(N.tokenize(stem)) == tag

    def test_level_numbers(self):
        assert N.level_numbers(N.tokenize("Keep_Level_2_Part_3")) == ("level#2", "part#3")


class TestAnalyseNames:
    def test_contradiction(self):
        tokens = [N.tokenize(s) for s in ["Forest_Road_1", "Forest_Gate_2", "Map_Vol1", "Map_Vol2"]]
        stems = ["a", "b", "c", "d"]
        ev = N.analyse_names(tokens, stems, [("f",)] * 4)
        assert ev.contradict(0, 1)  # different shared-base keys
        assert ev.contradict(2, 3)  # different series
        assert not ev.contradict(0, 0)

    def test_veto_keeps_the_level_designator(self):
        """ "Warehouse - Roof" has no 2-token key, but agreement must still be vetoed against
        another map's roof, as in E5 (the level word stays in the veto key)."""
        stems = ["Warehouse - Roof", "Spell Scroll Store - Roof", "Inn_Basement", "Inn_Roof"]
        ev = N.analyse_names([N.tokenize(s) for s in stems], stems, [("f",)] * 4)
        assert ev.full[0] == ("warehouse",) and ev.key2[0] is None
        assert ev.contradict(0, 1)
        assert ev.full[2] == ev.full[3] == ("inn",)

    def test_generic_numbering_has_no_identity(self):
        stems = [f"NumberedGLMaps_{k}" for k in range(50, 58)]
        ev = N.analyse_names([N.tokenize(s) for s in stems], stems, [("f",)] * 8)
        assert ev.full == [None] * 8
        assert all(ev.named)  # they have a name, it just carries no identity

    def test_counters_have_no_name(self):
        stems = ["IMG_0001", "DSC01234", "Cave_01"]
        ev = N.analyse_names([N.tokenize(s) for s in stems], stems, [("f",)] * 3)
        assert ev.full == [None, None, ("cave",)]
        assert ev.variant_only == [False, False, False]
