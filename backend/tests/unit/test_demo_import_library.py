"""The demo library import picks the right files and reports paths that group well."""

from scripts.demo.import_library import collect


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def test_collect_uses_vtt_copies_and_names_groups_after_the_map(tmp_path):
    maps, paintings = tmp_path / "maps", tmp_path / "paintings"
    _touch(maps / "Moonlight Maps" / "Hill Fort" / "VTT" / "Hill_Fort_Day.jpg")
    _touch(maps / "Moonlight Maps" / "Hill Fort" / "MA" / "Grid" / "Hill_Fort_Day_print.jpg")
    _touch(maps / "Moonlight Maps" / "Hill Fort" / "VTT" / "._Hill_Fort_Day.jpg")
    _touch(maps / "Fantasy Atlas" / "01 Above" / "FA-01-Day.jpg")
    _touch(paintings / "scenes" / "Ruined Church.jpg")

    found = {(reported, kind) for _, reported, kind in collect(maps, paintings)}

    assert found == {
        ("Moonlight Maps/Hill Fort/Hill_Fort_Day.jpg", "battlemap"),
        ("Fantasy Atlas/01 Above/FA-01-Day.jpg", "battlemap"),
        ("Scenes/Ruined Church.jpg", "scene"),
    }
