"""``import_metadata``: storing an import's Scene Atlas metadata and matching files to it
(design/export-backup-move.md §6)."""

import io
import json

import pytest

from backend.app.config import settings
from backend.app.models import ImportExportEntry, ImportJob, TagCategory
from backend.pipeline import import_metadata as im
from backend.pipeline import library_format as lf

H1, H2, ENC = "11" * 32, "22" * 32, "ee" * 32
GROUP = {"uid": "c" * 32, "base_name": "Forest", "author": "Czepeku"}


def _file(model=None, categories=(), lines=()) -> str:
    header = {
        "format": "scene-atlas",
        "version": "1.0",
        "kind": "groups",
        "app_version": "0.2.0",
        "created_at": "2026-11-03T00:00:00+00:00",
        "model": model,
        "tag_categories": list(categories),
    }
    return "".join(json.dumps(x) + "\n" for x in [header, *lines])


def _opener(text: str):
    return lambda: io.StringIO(text)


@pytest.fixture
def db(tmp_db, monkeypatch):
    """The job, and a session to look with; load_export writes through its own."""
    engine, SessionLocal = tmp_db
    monkeypatch.setattr(settings, "database_url", str(engine.url))
    monkeypatch.setattr(im, "_installed_model", lambda: (ENC, 2))
    with SessionLocal() as session:
        session.add(ImportJob(id="job1", source_label="x"))
        session.commit()
        yield session


def test_entries_are_stored_by_hash_and_matched_by_it(db):
    vector = lf.encode_vector([0.5, 0.25])
    lines = [
        {
            "group": GROUP,
            "images": [
                {
                    "filename": "a.png",
                    "name": "Day",
                    "stored_hash": H1,
                    "path": "F/a.png",
                    "vector": vector,
                },
                {"filename": "b.png", "name": "No hash"},  # can't be matched: not stored
            ],
        }
    ]
    model = {"name": "s", "encoder_sha256": ENC, "dim": 2}
    assert im.load_export("job1", _opener(_file(model, lines=lines))) == 1
    assert json.loads(db.get(ImportJob, "job1").export_model)["encoder_sha256"] == ENC

    matches = im.match_exports(db, "job1", [(7, H1, "a.png"), (8, H2, "c.png")])
    assert set(matches) == {7}
    assert matches[7].image.name == "Day" and matches[7].group.uid == "c" * 32
    assert matches[7].vector.tolist() == [0.5, 0.25]


def test_vectors_are_checked_against_the_model_installed_when_matching(db, monkeypatch):
    lines = [
        {
            "group": None,
            "images": [{"filename": "a", "stored_hash": H1, "vector": lf.encode_vector([1, 2])}],
        }
    ]
    im.load_export(
        "job1", _opener(_file({"name": "s", "encoder_sha256": ENC, "dim": 2}, lines=lines))
    )
    assert im.match_exports(db, "job1", [(1, H1, "a")])[1].vector is not None
    # The model was switched after the metadata loaded
    monkeypatch.setattr(im, "_installed_model", lambda: ("ff" * 32, 2))
    assert im.match_exports(db, "job1", [(1, H1, "a")])[1].vector is None


def test_one_hash_with_two_entries_prefers_the_one_named_like_the_file(db):
    lines = [
        {
            "group": None,
            "images": [
                {"filename": "x", "name": "First", "stored_hash": H1, "path": "A/first.png"},
                {"filename": "x", "name": "Second", "stored_hash": H1, "path": "B/second.png"},
            ],
        }
    ]
    im.load_export("job1", _opener(_file(lines=lines)))
    matches = im.match_exports(db, "job1", [(1, H1, "second.png"), (2, H1, "other.png")])
    assert matches[1].image.name == "Second"
    assert matches[2].image.name == "First"


def test_new_tag_categories_are_added_and_existing_ones_left_alone(db):
    categories = [
        {"name": "season", "description": "changed?", "color": "red"},  # seeded already
        {
            "name": "faction",
            "description": "Who holds it",
            "common_values": ["fey", {"value": "dwarf", "aliases": ["dwarven"]}],
        },
    ]
    im.load_export("job1", _opener(_file(categories=categories)))
    db.expire_all()
    assert db.query(TagCategory).filter_by(name="season").one().description != "changed?"
    faction = db.query(TagCategory).filter_by(name="faction").one()
    assert json.loads(faction.common_values) == ["fey", {"value": "dwarf", "aliases": ["dwarven"]}]


def test_a_file_that_cant_be_read_stores_nothing_and_leaves_a_note(db):
    good = {"group": None, "images": [{"filename": "a", "stored_hash": H1}]}
    assert im.load_export("job1", _opener(_file(lines=[good]) + "{broken\n")) == 0
    db.expire_all()
    job = db.get(ImportJob, "job1")
    assert db.query(ImportExportEntry).count() == 0
    assert job.export_model is None
    assert "couldn't be read" in job.export_note and "Line 3" in job.export_note


def test_a_bad_file_leaves_the_jobs_other_metadata_alone(db):
    good = {"group": None, "images": [{"filename": "a", "stored_hash": H1}]}
    files = [(_opener(_file(lines=[good])), "One"), (_opener("not json\n"), "Two")]
    assert im.load_exports("job1", files) == 1
    db.expire_all()
    assert db.query(ImportExportEntry).count() == 1
    assert db.get(ImportJob, "job1").export_note is not None
    assert set(im.match_exports(db, "job1", [(1, H1, "a")])) == {1}


def test_entries_go_with_their_job(db):
    im.load_export(
        "job1",
        _opener(_file(lines=[{"group": None, "images": [{"filename": "a", "stored_hash": H1}]}])),
    )
    im.delete_entries(db, ["job1"])
    assert db.query(ImportExportEntry).count() == 0


@pytest.mark.parametrize(
    "path", ["scene-atlas.jsonl", "Pack/scene-atlas.jsonl", "A/B/scene-atlas.jsonl"]
)
def test_is_metadata_file(path):
    assert im.is_metadata_file(path)
    assert not im.is_metadata_file("Pack/scene-atlas.jsonl.bak")
