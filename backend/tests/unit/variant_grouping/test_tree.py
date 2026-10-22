"""Unit tests for variant_grouping.tree: the effective folder tree."""

from backend.app.services.variant_grouping.names import FolderClass
from backend.app.services.variant_grouping.tree import build_tree


def eff(*paths: str) -> list[tuple[str, ...]]:
    """Effective folder of each raw folder path ("a/b/c")."""
    raws = [tuple(p.split("/")) for p in paths]
    tree = build_tree(raws)
    return [tree.effective_of[r] for r in raws]


class TestTransparentFolders:
    def test_rendition_folders_belong_to_their_parent(self):
        assert (
            eff(
                "Maker/Forest Road/Gridded",
                "Maker/Forest Road/VTT",
                "Maker/Forest Road/MA/No Grid",
                "Maker/Forest Road/70 DPI (VTT)",
            )
            == [("maker", "forest road")] * 4
        )

    def test_parent_name_plus_size_is_a_rendition(self):
        """``Beast Prison 12x12`` under ``Beast Prison`` (audit: Never Ending Wizard Tower)."""
        assert eff("Tower/Beast Prison/Beast Prison 12x12/MA/Grid") == [("tower", "beast prison")]

    def test_misspelt_parent_name_is_a_rendition(self):
        assert eff("Maker/Colossus/Colossas Gridded") == [("maker", "colossus")]

    def test_variant_folders_are_transparent(self):
        assert (
            eff("Maker/Forest Road/Night", "Maker/Forest Road/Gridded Winter")
            == [("maker", "forest road")] * 2
        )

    def test_top_level_axis_split(self):
        """The library split by grid or time at the top: ``Gridded/X`` and ``Night/X``."""
        assert (
            eff("Gridded/Swamp Hut", "Gridless/Swamp Hut", "Night/Swamp Hut")
            == [("swamp hut",)] * 3
        )

    def test_specific_child_stays_without_its_size(self):
        assert eff("Tower/Teleport Room/Teleport Chamber 12x12") == [
            ("tower", "teleport room", "teleport chamber")
        ]


class TestMirrorCollapse:
    def test_mirror_siblings_collapse(self):
        a, b = eff("Maker/Forest Road Gridded", "Maker/Forest Road Gridless")
        assert a == b == ("maker", "forest road")

    def test_numbered_siblings_stay_apart(self):
        a, b = eff("Maker/Dungeon Room 1", "Maker/Dungeon Room 2")
        assert a != b


class TestTreeRecords:
    def test_children_and_names(self):
        tree = build_tree([("Maker", "Forest Road Gridded"), ("Maker", "Forest Road Gridless")])
        assert tree.children[("maker",)] == {("maker", "forest road")}
        assert tree.raw_names[("maker", "forest road")] == {
            "Forest Road Gridded",
            "Forest Road Gridless",
        }

    def test_name_class(self):
        tree = build_tree([("Moonlight Maps", "Pack 02"), ("Moonlight Maps", "Forest Road")])
        assert tree.name_class[("moonlight maps", "pack 02")] is FolderClass.GENERIC
        assert tree.name_class[("moonlight maps", "forest road")] is FolderClass.SPECIFIC

    def test_recurring_names(self):
        """An author folder under several topics, with >= 2 children each, recurs."""
        tree = build_tree(
            [
                ("Woods", "Moonlight Maps", "Forest Road"),
                ("Woods", "Moonlight Maps", "Forest Switch"),
                ("Caves", "Moonlight Maps", "Deep Cave"),
                ("Caves", "Moonlight Maps", "Crystal Cavern"),
                ("Caves", "Solo Maker", "Goblin Den"),
            ]
        )
        assert tree.recurring_names() == {"moonlight maps"}
