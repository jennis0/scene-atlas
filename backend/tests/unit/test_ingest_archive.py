"""Where zip members land (``place_members``, design/ingestion.md §7)."""

from backend.pipeline.ingest_archive import place_members


def placed(paths: list[str], archive_name: str) -> list[str]:
    return [place_members(paths, archive_name)[p] for p in paths]


def test_flat_zip_is_placed_under_its_name():
    assert placed(["Day.png", "Night.png"], "Golden Forest.zip") == [
        "Golden Forest/Day.png",
        "Golden Forest/Night.png",
    ]


def test_zip_folder_comes_first():
    assert placed(["Day.png"], "czepeku/Golden Forest.zip") == ["czepeku/Golden Forest/Day.png"]


def test_folder_repeating_the_zip_name_is_dropped():
    paths = ["Golden Forest [30x30] - $5 Rewards/Day.png", "GoldenForest/Night.png"]
    assert placed(paths, "Creator/Golden Forest.zip") == [
        "Creator/Golden Forest/Day.png",
        "Creator/Golden Forest/Night.png",
    ]


def test_generic_folders_are_kept_under_the_zip_name():
    assert placed(["Gridded/a.png", "Gridless/a.png"], "Golden Forest.zip") == [
        "Golden Forest/Gridded/a.png",
        "Golden Forest/Gridless/a.png",
    ]


def test_informative_folders_keep_their_paths():
    paths = ["Pack/Island Fort/a.png", "Pack/Dark Cave/b.png"]
    assert placed(paths, "Creator/Pack.zip") == paths


def test_only_media_folders_decide():
    """A licence folder doesn't make a single map's zip a collection."""
    assert placed(["Day.png", "License/readme.txt"], "Golden Forest.zip") == [
        "Golden Forest/Day.png",
        "Golden Forest/License/readme.txt",
    ]
