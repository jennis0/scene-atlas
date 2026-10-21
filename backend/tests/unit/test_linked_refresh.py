"""Re-detecting the grid of an edited linked file (backend/pipeline/linked_refresh.py,
design/library-setup.md §4.5): the rules are the forced backfill's (ADR-019)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models import Image, ImageGroup, LibrarySource, SourceFile
from backend.pipeline import ingest_process, linked_refresh
from backend.pipeline.linked_refresh import RefreshTarget, load_targets, refresh_grid
from backend.pipeline.pipeline_config import PipelineConfig

ON = PipelineConfig(enable_image_grid_detection=True)
OFF = PipelineConfig(enable_image_grid_detection=False)
PATH = Path("map.png")

CLEARED = {
    "gridded": None,
    "grid_width": None,
    "grid_height": None,
    "grid_type": None,
    "grid_confidence": None,
    "grid_source": None,
}


def target(**kw) -> RefreshTarget:
    fields = {
        "image_id": 1,
        "content_hash": "h" * 64,
        "image_type": "battlemap",
        "media_type": "image",
        "gridded": None,
        "grid_width": None,
        "grid_height": None,
        "grid_type": None,
        "grid_confidence": None,
        "grid_source": None,
    }
    return RefreshTarget(**(fields | kw))


class Detector:
    """A detector that finds a 30x20 square grid, recording how it was called."""

    def __init__(self):
        self.calls: list[dict] = []
        self.result = {
            "gridded": True,
            "grid_type": "square",
            "grid_width": 30,
            "grid_height": 20,
            "confidence": 0.9,
        }

    def __call__(self, path, width, height, **kw):
        self.calls.append(kw)
        return dict(self.result)


@pytest.fixture
def detector(monkeypatch) -> Detector:
    detect = Detector()
    monkeypatch.setattr(linked_refresh.grid_detection, "detect_grid_from_image", detect)
    return detect


@pytest.mark.parametrize(
    "kept",
    [
        {"grid_source": "user", "gridded": True, "grid_width": 10, "grid_height": 8},
        {"grid_source": "filename", "gridded": False},  # "No Grid" in the name
        {"grid_source": "detector", "gridded": True, "image_type": "scene"},
        {"media_type": "video"},
    ],
)
def test_labels_and_other_types_are_kept(detector, kept):
    assert refresh_grid(target(**kept), PATH, 3000, 2000, ON) == {}
    assert detector.calls == []


def test_a_file_names_exact_size_is_kept_and_turned_with_the_image(detector):
    named = target(grid_source="filename", gridded=True, grid_width=30, grid_height=20)
    assert refresh_grid(named, PATH, 3000, 2000, ON) == {}
    # The edited file is portrait now: the longer side of the grid follows it
    assert refresh_grid(named, PATH, 2000, 3000, ON) == {"grid_width": 20, "grid_height": 30}
    assert detector.calls == []


def test_a_detected_grid_is_detected_again(detector):
    detected = target(grid_source="detector", gridded=True, grid_width=12, grid_height=9)
    assert refresh_grid(detected, PATH, 3000, 2000, ON) == {
        "gridded": True,
        "grid_width": 30,
        "grid_height": 20,
        "grid_type": "square",
        "grid_confidence": 0.9,
        "grid_source": "detector",
    }
    assert detector.calls[0]["size_only"] is False
    assert refresh_grid(target(), PATH, 3000, 2000, ON)["grid_source"] == "detector"


def test_nothing_detected_drops_the_old_detection(detector):
    detector.result.update(gridded=None, grid_width=None, grid_height=None, confidence=0.0)
    detected = target(grid_source="detector", gridded=True, grid_width=12, grid_height=9)
    assert refresh_grid(detected, PATH, 3000, 2000, ON) == CLEARED


def test_a_named_grid_gets_its_size_detected_again(detector):
    named = target(
        grid_source="filename", gridded=True, grid_type="square", sibling_counts=((30, 20),)
    )
    assert refresh_grid(named, PATH, 3000, 2000, ON) == {
        "grid_width": 30,
        "grid_height": 20,
        "grid_type": "square",
        "grid_confidence": 0.9,
    }
    assert detector.calls[0] == {
        "size_only": True,
        "pipeline_config": ON,
        "sibling_counts": ((30, 20),),
    }
    # A size detected before is detected again too
    sized = replace(named, grid_width=12, grid_height=9, grid_confidence=0.7)
    assert refresh_grid(sized, PATH, 3000, 2000, ON)["grid_width"] == 30


def test_detection_off_drops_what_was_detected(detector):
    detected = target(grid_source="detector", gridded=True, grid_width=12, grid_height=9)
    assert refresh_grid(detected, PATH, 3000, 2000, OFF) == CLEARED
    sized = target(grid_source="filename", gridded=True, grid_width=12, grid_height=9)
    sized = replace(sized, grid_confidence=0.7)
    # "gridded" is the file name's: only the detected size goes
    assert refresh_grid(sized, PATH, 3000, 2000, OFF) == {
        "grid_width": None,
        "grid_height": None,
        "grid_confidence": None,
    }
    assert detector.calls == []


def test_targets_are_the_images_of_files(db_session):
    db = db_session
    source = LibrarySource(kind="folder", location="/maps", state="online")
    group = ImageGroup(base_name="Forest")
    db.add_all([source, group])
    db.flush()
    rows = [
        SourceFile(source_id=source.id, rel_key=key, size=1, mtime_ns=1, state="image")
        for key in ("A/named.png", "A/sibling.png", "A/new.png")
    ]
    db.add_all(rows)
    db.flush()
    named = Image(
        filename="named.png",
        source_file_id=rows[0].id,
        group_id=group.id,
        content_hash="a" * 64,
        gridded=True,
        grid_source="filename",
    )
    sibling = Image(
        filename="sibling.png",
        source_file_id=rows[1].id,
        group_id=group.id,
        gridded=True,
        grid_width=30,
        grid_height=20,
        grid_source="filename",
    )
    db.add_all([named, sibling])
    db.flush()

    targets = load_targets(db, [row.id for row in rows])
    assert set(targets) == {rows[0].id, rows[1].id}  # the new file has no image
    assert targets[rows[0].id].image_id == named.id
    assert targets[rows[0].id].content_hash == "a" * 64
    # Size-only detection gets the group's named sizes, both ways round
    assert set(targets[rows[0].id].sibling_counts) == {(30, 20), (20, 30)}
    assert targets[rows[1].id].sibling_counts == ()  # an exact NxM isn't re-detected
    assert load_targets(db, []) == {}


class _Vectors:
    def __init__(self, ok: bool):
        self.ok = ok
        self.deleted: list[int] = []

    def batch_add_embeddings(self, items):
        return self.ok

    def delete_embeddings(self, image_ids):
        self.deleted += image_ids
        return True


@pytest.mark.parametrize("ok", [True, False])
def test_a_refreshed_images_old_vector_never_outlives_a_failed_write(monkeypatch, ok):
    """Reconciliation embeds images without a vector: a stale one would never be fixed."""
    vectors = _Vectors(ok)
    monkeypatch.setattr(ingest_process, "get_lancedb_service", lambda: vectors)
    prepared = SimpleNamespace(
        decoded=SimpleNamespace(embedding=[0.1] * 8), item=SimpleNamespace(filename="x.png")
    )
    done = [ingest_process.CommittedImage(prepared, 7, None, None)]  # type: ignore[arg-type]
    assert ingest_process.write_vectors(done, refreshed=[7]) is ok
    assert vectors.deleted == ([] if ok else [7])
