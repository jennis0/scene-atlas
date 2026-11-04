"""Migration 030 gives every existing group a distinct uid without rebuilding the table, so
the group image-count triggers keep working, and it downgrades cleanly."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.config_file_name = None  # don't let Alembic reconfigure logging
    return cfg


def _add_image(conn, name: str, group_id: int) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO images (filename, name, storage_key, variant_group_id) "
            "VALUES (:name, :name, :name, :gid)"
        ),
        {"name": name, "gid": group_id},
    )


def test_upgrade_backfills_unique_uids_and_downgrade_removes_them(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "029")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        for gid, name in ((1, "Fort"), (2, "Forest"), (3, "Tavern")):
            conn.execute(
                sa.text(
                    "INSERT INTO variant_groups (id, base_name, image_count) VALUES (:i, :n, 0)"
                ),
                {"i": gid, "n": name},
            )
        _add_image(conn, "Fort Day", 1)

    command.upgrade(cfg, "030")

    with engine.begin() as conn:
        uids = [u for (u,) in conn.execute(sa.text("SELECT uid FROM variant_groups ORDER BY id"))]
        assert len(uids) == 3
        assert len(set(uids)) == 3
        assert all(len(u) == 32 and int(u, 16) >= 0 for u in uids)
        # The triggers on images still maintain the group's count
        _add_image(conn, "Fort Night", 1)
        count = conn.execute(sa.text("SELECT image_count FROM variant_groups WHERE id = 1"))
        assert count.scalar() == 2
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("UPDATE variant_groups SET uid = :u WHERE id = 2"), {"u": uids[0]})

    command.downgrade(cfg, "029")

    with engine.begin() as conn:
        columns = {c["name"] for c in sa.inspect(conn).get_columns("variant_groups")}
        assert "uid" not in columns
