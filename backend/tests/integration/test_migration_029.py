"""Migration 029 (variant grouping) adds a table and two columns without rebuilding any
table, so the triggers on images keep working, and it downgrades cleanly."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.config_file_name = None  # don't let Alembic reconfigure logging
    return cfg


def _columns(conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(table)}


def _image_count(conn) -> int:
    return conn.execute(sa.text("SELECT image_count FROM variant_groups WHERE id = 1")).scalar()


def _add_image(conn, name: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO images (filename, name, storage_key, variant_group_id) "
            "VALUES (:name, :name, :name, 1)"
        ),
        {"name": name},
    )


def _search(conn, word: str) -> list[str]:
    rows = conn.execute(
        sa.text(
            "SELECT images.name FROM image_fts JOIN images ON images.id = image_fts.rowid "
            "WHERE image_fts MATCH :q ORDER BY images.name"
        ),
        {"q": word},
    )
    return [name for (name,) in rows]


def test_upgrade_keeps_triggers_and_downgrade_removes_the_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "028")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO variant_groups (id, base_name, image_count) VALUES (1, 'Fort', 0)")
        )
        _add_image(conn, "Fort Day")

    command.upgrade(cfg, "029")

    with engine.begin() as conn:
        assert "grouped_at" in _columns(conn, "import_jobs")
        assert "awaiting_grouping" in _columns(conn, "images")
        assert _columns(conn, "image_grouping_features") == {
            "image_id",
            "version",
            "phash256",
            "edge",
        }
        # The rows came through and the triggers on images still fire
        assert _image_count(conn) == 1
        _add_image(conn, "Fort Night")
        assert _image_count(conn) == 2
        assert _search(conn, "night") == ["Fort Night"]
        conn.execute(
            sa.text(
                "INSERT INTO image_grouping_features (image_id, version, phash256) "
                "VALUES (1, 1, :hash)"
            ),
            {"hash": bytes(32)},
        )

    command.downgrade(cfg, "028")

    with engine.begin() as conn:
        assert "image_grouping_features" not in sa.inspect(conn).get_table_names()
        assert "grouped_at" not in _columns(conn, "import_jobs")
        assert "awaiting_grouping" not in _columns(conn, "images")
        conn.execute(sa.text("DELETE FROM images WHERE name = 'Fort Day'"))
        assert _image_count(conn) == 1
        assert _search(conn, "day") == []


def _seed_imports(conn) -> None:
    """At 028: a finished import, one still running and one not sealed yet, each with a
    gallery group of imported maps."""
    for job_id, status, planned, completed in (
        ("done", "completed", "2026-10-01 10:00:00", "2026-10-01 11:00:00"),
        ("running", "active", "2026-10-02 10:00:00", None),
        ("unsealed", "active", None, None),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO import_jobs (id, status, default_image_type, planned_at, "
                "completed_at) VALUES (:id, :status, 'battlemap', :planned, :completed)"
            ),
            {"id": job_id, "status": status, "planned": planned, "completed": completed},
        )
    conn.execute(
        sa.text("INSERT INTO variant_groups (id, base_name, image_count) VALUES (1, 'Fort', 0)")
    )
    conn.execute(
        sa.text("INSERT INTO variant_groups (id, base_name, image_count) VALUES (2, 'Keep', 0)")
    )
    for group_id, job_id in ((1, "done"), (2, "running")):
        conn.execute(
            sa.text(
                "INSERT INTO import_groups (id, job_id, group_name, image_group_id, "
                "merged_into_existing, sort_order) VALUES (:id, :job, 'G', :id, 0, 0)"
            ),
            {"id": group_id, "job": job_id},
        )
    rows = (
        # (item, job, group, state, image)
        (1, "done", 1, "done", 1),
        (2, "done", 1, "done", 2),
        (3, "running", 2, "done", 3),
        (4, "running", 2, "ready", None),
    )
    for item_id, job_id, group_id, state, image_id in rows:
        if image_id is not None:
            conn.execute(
                sa.text(
                    "INSERT INTO images (id, filename, name, storage_key, variant_group_id, "
                    "import_job_id, image_type) VALUES (:id, :f, :f, :f, :g, :job, 'battlemap')"
                ),
                {"id": image_id, "f": f"m{image_id}.png", "g": group_id, "job": job_id},
            )
        conn.execute(
            sa.text(
                "INSERT INTO import_items (id, job_id, import_group_id, kind, relative_path, "
                "filename, image_type, state, attempts, allow_duplicate, image_id) VALUES "
                "(:id, :job, :g, 'image', :path, :path, 'battlemap', :state, 0, 0, :image)"
            ),
            {
                "id": item_id,
                "job": job_id,
                "g": group_id,
                "path": f"A/G/{item_id}.png",
                "state": state,
                "image": image_id,
            },
        )


def test_imports_sealed_before_029_are_already_grouped(tmp_path, monkeypatch):
    """Every finished job is stamped grouped, so none enters the grouping phase and its groups
    stay as they are. One still running finishes into the groups its seal planned."""
    from sqlalchemy.orm import Session

    from backend.app.api.imports import _summaries
    from backend.app.models import Image, ImageGroup, ImportItem, ImportJob
    from backend.pipeline import group_jobs
    from backend.pipeline import ingest_queue as q

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "028")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        _seed_imports(conn)
    command.upgrade(cfg, "029")

    with Session(engine) as db:
        jobs = {j.id: j for j in db.query(ImportJob)}
        assert {j: jobs[j].grouped_at is not None for j in jobs} == {
            "done": True,
            "running": False,  # it will group what it still imports
            "unsealed": False,
        }
        assert group_jobs.due_jobs(db) == []
        assert {i.awaiting_grouping for i in db.query(Image)} == {False}
        summaries = {s.id: s for s in _summaries(db, list(jobs.values()))}
        assert summaries["done"].groups_reviewable == 1  # reviewable as before

        # The running import's last file commits ungrouped, then the job finishes
        db.add(
            Image(
                id=4,
                filename="m4.png",
                name="m4",
                storage_key="m4.png",
                import_job_id="running",
                image_type="battlemap",
                awaiting_grouping=True,
            )
        )
        item = db.get_one(ImportItem, 4)
        item.state, item.image_id = "done", 4
        q.recompute_job_status(db, "running")
        db.commit()
        assert db.get_one(ImportJob, "running").status == "grouping"
        assert group_jobs.due_jobs(db) == ["running"]

    monkeypatch.setattr("backend.app.config.settings.database_url", url)
    assert group_jobs.group_job("running", readiness=lambda: group_jobs.Readiness.OFF) == (
        group_jobs.Outcome.GROUPED
    )
    with Session(engine) as db:
        image = db.get_one(Image, 4)
        assert (image.group_id, image.awaiting_grouping) == (2, False)  # its seal's group
        assert db.query(ImageGroup).count() == 2
        assert db.get_one(ImportJob, "running").status == "completed"
    engine.dispose()
