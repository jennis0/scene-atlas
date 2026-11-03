"""The readable layout (design/export-backup-move.md §3): names, grid codes, length limits
and collisions."""

from types import SimpleNamespace

import pytest

from backend.pipeline.naming import (
    FILE_MAX,
    FOLDER_MAX,
    PATH_MAX,
    LayoutImage,
    ReadableLayout,
    grid_code,
    layout_image,
    readable_stem,
)


def _img(name="Day", subgroup=None, grid="G30x30", tags=(), ext=".webp") -> LayoutImage:
    return LayoutImage(name=name, subgroup=subgroup, grid=grid, tags=tuple(tags), ext=ext)


class TestGridCode:
    @pytest.mark.parametrize(
        ("args", "code"),
        [
            ((True, "square", 30, 30), "G30x30"),
            ((True, None, 20, 15), "G20x15"),
            ((True, "hex", 20, 15), "HG20x15"),
            ((True, "square", None, None), "G"),
            ((True, "hex", 20, None), "HG"),
            ((False, None, None, None), "GL"),
            ((None, None, None, None), ""),
        ],
    )
    def test_codes(self, args, code):
        assert grid_code(*args) == code


class TestReadableStem:
    def test_all_parts(self):
        stem = readable_stem("Czepeku", "Golden Forest", "Winter", "Day", "G30x30", ["snow"], 150)
        assert stem == "Czepeku_Golden Forest_Winter_Day_G30x30[snow]"

    def test_missing_parts_are_left_out(self):
        assert readable_stem(None, None, None, "Harbour", "", [], 150) == "Harbour"
        assert readable_stem("", "Forest", None, "Day", "GL", [], 150) == "Forest_Day_GL"

    def test_name_equal_to_group_is_not_repeated(self):
        stem = readable_stem(
            "Czepeku", "Lone Tavern", None, "lone tavern", "HG20x15", ["urban"], 150
        )
        assert stem == "Czepeku_Lone Tavern_HG20x15[urban]"

    def test_underscores_and_unsafe_characters_become_spaces(self):
        stem = readable_stem("Tom_Cartos", "Ship: Wreck", None, "Day/Night", "G", [], 150)
        assert stem == "Tom Cartos_Ship Wreck_Day Night_G"

    def test_tags_are_dropped_from_the_end_first(self):
        stem = readable_stem("A", "Group", None, "Name", "G", ["alpha", "beta", "gamma"], 25)
        assert stem == "A_Group_Name_G[alpha]"

    def test_then_the_name_then_the_group_is_shortened(self):
        stem = readable_stem("A", "Group", None, "A Very Long Name Indeed", "G", ["x"], 20)
        assert len(stem) <= 20
        assert stem.startswith("A_Group_A")
        assert stem.endswith("_G")
        tiny = readable_stem("A", "A Long Group Name", None, "A Long Name", "G", [], 10)
        assert len(tiny) <= 10

    def test_control_characters_are_removed(self):
        assert readable_stem(None, None, None, "Bad\x00Name\x1f\x7f", "", [], 150) == "Bad Name"

    def test_windows_reserved_names_and_trailing_dots(self):
        assert readable_stem(None, None, None, "CON", "", [], 150) == "CON-"
        assert readable_stem(None, None, None, "Ends with dots...", "", [], 150) == "Ends with dots"
        assert readable_stem(None, None, None, "", "", [], 150) == "image"


class TestReadableLayout:
    def test_a_group_gets_a_folder(self):
        paths = ReadableLayout().place_group(
            "Golden Forest", "Czepeku", [_img("Day", tags=["summer"]), _img("Night", grid="GL")]
        )
        assert paths == [
            "Czepeku_Golden Forest/Czepeku_Golden Forest_Day_G30x30[summer].webp",
            "Czepeku_Golden Forest/Czepeku_Golden Forest_Night_GL.webp",
        ]

    def test_a_group_of_one_and_ungrouped_images_sit_at_the_top(self):
        layout = ReadableLayout()
        assert layout.place_group(
            "Lone Tavern", "Czepeku", [_img("Lone Tavern", grid="HG20x15")]
        ) == ["Czepeku_Lone Tavern_HG20x15.webp"]
        assert layout.place_group(None, "Tom Cartos", [_img("Harbour", grid="G", ext=".jpg")]) == [
            "Tom Cartos_Harbour_G.jpg"
        ]

    def test_folder_collisions_are_case_insensitive_and_numbered_in_order(self):
        layout = ReadableLayout()
        first = layout.place_group("Forest", "Czepeku", [_img("Day"), _img("Night")])
        second = layout.place_group("forest", "czepeku", [_img("Day"), _img("Night")])
        assert first[0].split("/")[0] == "Czepeku_Forest"
        assert second[0].split("/")[0] == "czepeku_forest (2)"

    def test_file_collisions_in_a_folder_are_numbered(self):
        paths = ReadableLayout().place_group(
            "Forest", None, [_img("Day"), _img("day"), _img("Day")]
        )
        assert [p.split("/")[1] for p in paths] == [
            "Forest_Day_G30x30.webp",
            "Forest_day_G30x30 (2).webp",
            "Forest_Day_G30x30 (3).webp",
        ]

    def test_many_clashes_number_on_without_rescanning(self):
        layout = ReadableLayout()
        paths = [layout.place_group(None, None, [_img("Map")])[0] for _ in range(5_000)]
        assert len({p.casefold() for p in paths}) == 5_000
        assert paths[:3] == ["Map_G30x30.webp", "Map_G30x30 (2).webp", "Map_G30x30 (3).webp"]
        assert paths[-1] == "Map_G30x30 (5000).webp"

    def test_names_already_on_disk_are_avoided(self):
        layout = ReadableLayout(taken=["CZEPEKU_FOREST"])
        paths = layout.place_group("Forest", "Czepeku", [_img("Day"), _img("Night")])
        assert paths[0].startswith("Czepeku_Forest (2)/")

    def test_lengths_stay_within_the_limits(self):
        long = "x" * 300
        layout = ReadableLayout(root_len=120)
        paths = layout.place_group(long, long, [_img(long, tags=[long] * 5), _img(long + "y")])
        for path in paths:
            folder, name = path.split("/")
            assert len(folder) <= FOLDER_MAX
            assert len(name) <= FILE_MAX
            assert 120 + 1 + len(path) <= PATH_MAX
        assert paths[0] != paths[1]


def test_layout_image_orders_tags_by_category_and_keeps_the_stored_extension():
    img = SimpleNamespace(
        name="Day",
        subgroup=None,
        gridded=True,
        grid_type="square",
        grid_width=30,
        grid_height=30,
        storage_key="3f9a.webp",
        filename="Day.png",
        tags=[
            SimpleNamespace(category="season", value="summer"),
            SimpleNamespace(category="biome", value="forest, deep"),
            SimpleNamespace(category="biome", value="[river]"),
        ],
    )
    li = layout_image(img, {"biome": 0, "season": 1})
    assert li.tags == ("forest deep", "river", "summer")
    assert li.grid == "G30x30"
    assert li.ext == ".webp"


@pytest.mark.parametrize(
    ("filename", "ext"),
    [
        ("map.PNG", ".PNG"),
        ("map", ""),
        ("map.tar.gz", ".gz"),
        ("odd.<ext>", ""),
        ("x.12345678901", ""),
    ],
)
def test_layout_image_only_keeps_plain_extensions(filename, ext):
    img = SimpleNamespace(
        name="m", subgroup=None, gridded=None, grid_type=None, grid_width=None,
        grid_height=None, storage_key=None, filename=filename, tags=[],
    )  # fmt: skip
    assert layout_image(img).ext == ext


def test_names_that_differ_only_in_unicode_form_are_kept_apart():
    """macOS' file systems treat NFC and NFD as one name: so must the layout."""
    import unicodedata

    layout = ReadableLayout()
    nfc = layout.place_group(unicodedata.normalize("NFC", "Café"), "A", [_img(), _img("Night")])
    nfd = layout.place_group(unicodedata.normalize("NFD", "Café"), "A", [_img(), _img("Night")])
    assert nfc[0].split("/")[0] == "A_Café"
    assert nfd[0].split("/")[0] == "A_Café (2)"
    assert unicodedata.is_normalized("NFC", nfd[0])


@pytest.mark.parametrize("name", ["Long " * 60, "🐉" * 120])
def test_paths_leave_room_for_the_part_file_in_windows_units(name):
    root_len = 120
    layout = ReadableLayout(root_len=root_len)
    (path,) = layout.place_group(None, "Author", [_img(name=name)])
    windows_len = root_len + 1 + len(path.encode("utf-16-le")) // 2 + len(".part")
    assert windows_len <= 259


@pytest.mark.parametrize("stem", ["COM0", "LPT¹", "CONIN$", "conout$"])
def test_more_reserved_windows_names(stem):
    from backend.pipeline.naming import _safe_stem

    assert _safe_stem(stem) != stem
