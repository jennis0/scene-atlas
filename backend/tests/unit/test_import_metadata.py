"""``import_metadata``: storing an import's Scene Atlas metadata and matching files to it
(design/export-backup-move.md §6)."""

import gzip
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
    assert im.load_export("job1", _opener(_file(lines=[good]))) == 1
    assert im.load_export("job1", _opener("not json\n")) == 0
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


GOOD = {"group": None, "images": [{"filename": "a", "stored_hash": H1}]}


def test_a_corrupt_gzip_leaves_a_note_and_doesnt_raise(db, tmp_path):
    path = tmp_path / "scene-atlas.jsonl.gz"
    packed = gzip.compress(_file(lines=[GOOD]).encode())
    path.write_bytes(packed[:20] + b"garbage" * 10 + packed[-8:])
    assert im.load_export("job1", im.file_opener(path)) == 0
    db.expire_all()
    assert "couldn't be read" in db.get(ImportJob, "job1").export_note


def test_a_file_that_changes_after_validating_keeps_nothing(db, monkeypatch):
    monkeypatch.setattr(im, "_BATCH", 1)  # so a batch is stored before it goes wrong
    reads = iter([_file(lines=[GOOD, GOOD]), _file(lines=[GOOD]) + "{broken\n"])
    assert im.load_export("job1", lambda: io.StringIO(next(reads))) == 0
    db.expire_all()
    assert db.query(ImportExportEntry).count() == 0
    assert db.get(ImportJob, "job1").export_note is not None


def test_a_job_deleted_while_loading_keeps_nothing(db, monkeypatch):
    monkeypatch.setattr(im, "_BATCH", 1)
    real = im._write
    batches = []

    def write(fn):
        real(fn)
        batches.append(1)
        if len(batches) == 3:  # the stale-row delete, then a batch stored: now it goes
            db.query(ImportJob).filter_by(id="job1").delete()
            db.commit()

    monkeypatch.setattr(im, "_write", write)
    assert im.load_export("job1", _opener(_file(lines=[GOOD, GOOD, GOOD]))) == 0
    db.expire_all()
    assert db.query(ImportExportEntry).count() == 0


def test_an_interrupted_load_is_replaced_not_doubled(db):
    """A restart loads the file again under the same source: what the first run stored
    goes first."""
    text = _file(lines=[GOOD])
    im.load_export("job1", _opener(text), source="s" * 32)
    im.load_export("job1", _opener(text), source="s" * 32)
    assert db.query(ImportExportEntry).count() == 1


def test_large_files_are_stored_in_batches(db, monkeypatch):
    monkeypatch.setattr(im, "_BATCH", 2)
    writes = []
    real = im._write
    monkeypatch.setattr(im, "_write", lambda fn: writes.append(1) or real(fn))
    images = [{"filename": f"{i}.png", "stored_hash": f"{i:064x}"} for i in range(5)]
    assert im.load_export("job1", _opener(_file(lines=[{"group": None, "images": images}]))) == 5
    assert len(writes) == 5  # stale rows cleared, three batches, then categories and model


def test_pending_files_hold_the_job_and_load_one_at_a_time(db, tmp_path, monkeypatch):
    from backend.pipeline import ingest_queue as q

    monkeypatch.setattr(
        "backend.pipeline.ingest_worker.get_ingest_worker",
        lambda: type("W", (), {"wake": lambda self: None})(),
    )
    files = [tmp_path / "one.jsonl", tmp_path / "two.jsonl"]
    files[0].write_text(_file(lines=[GOOD]))
    files[1].write_text(
        _file(lines=[{"group": None, "images": [{"filename": "b", "stored_hash": H2}]}])
    )
    job = db.get(ImportJob, "job1")
    im.add_pending(db, job, files[:1])
    im.add_pending(db, job, files[1:], delete=False)
    im.add_pending(db, job, [tmp_path / "arriving.jsonl"], ready=False)
    job.planned_at = q.utcnow()
    db.commit()

    im.recover_pending()  # forgets the file still arriving, then loads the rest
    assert im.wait_for_loads(10)
    db.expire_all()
    assert db.get(ImportJob, "job1").metadata_pending is None
    assert db.query(ImportExportEntry).count() == 2
    assert not files[0].exists() and files[1].exists()  # the staging copy goes


def test_the_job_is_held_while_files_are_pending(db):
    from backend.app.models import ImportItem
    from backend.pipeline import ingest_queue as q

    job = db.get(ImportJob, "job1")
    job.planned_at = q.utcnow()
    db.add(
        ImportItem(
            job_id="job1", relative_path="a.png", filename="a.png", kind="image", state="ready"
        )
    )
    job.metadata_pending = json.dumps([{"path": "/x", "ready": False, "delete": True}])
    db.commit()
    assert "job1" not in q._claimable_jobs(db, q.utcnow())
    job.metadata_pending = None
    db.commit()
    assert "job1" in q._claimable_jobs(db, q.utcnow())
