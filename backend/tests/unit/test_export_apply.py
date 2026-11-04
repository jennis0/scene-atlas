"""Applying an import's metadata entry to a file (ingest_process; design/export-backup-move.md
§6): its text is untrusted, so what it names is made safe."""

import pytest

from backend.pipeline import ingest_process as ip
from backend.pipeline import library_format as lf


@pytest.mark.parametrize(
    ("recorded", "expected"),
    [
        ("Forest Day.png", "Forest Day.png"),
        (None, "now.png"),
        ("", "now.png"),
        ("../../etc/Forest.png", "Forest.png"),  # a name, never a path
        ("C:\\\\maps\\\\Forest.PNG", "Forest.PNG"),
        ("Forest\x00\x1b.png", "Forest .png"),  # control characters go
        ("Forest.jpg", "now.png"),  # another type than the bytes
        ("x" * 300 + ".png", "now.png"),
    ],
)
def test_restored_filename(recorded, expected):
    assert ip.restored_filename(recorded, "now.png") == expected


def test_tags_are_cut_to_the_api_limit_once_each():
    long = "x" * 150
    image = lf.ImageEntry.model_validate(
        {
            "filename": "a.png",
            "tags": [
                {"category": "season", "value": long + "a"},
                {"category": "season", "value": long + "b"},  # the same, once cut
                {"category": "theme", "value": "fey", "source": "auto", "confidence": 0.5},
            ],
        }
    )
    tags = ip._export_tags(image)
    assert [(t["category"], t["value"]) for t in tags] == [("season", "x" * 100), ("theme", "fey")]
    assert tags[1]["source"] == "auto" and tags[1]["confidence"] == 0.5
