"""Migration 028 (the linked library) rebuilds the images table: its triggers must
survive, and an image needs a stored original or a linked file."""

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


def _insert_image(conn, name: str, group_id: int, **extra) -> None:
    columns = {"filename": name, "name": name, "variant_group_id": group_id, **extra}
    images = sa.table("images", *(sa.column(c) for c in columns))
    conn.execute(images.insert().values(**columns))


def _search(conn, word: str) -> list[str]:
    rows = conn.execute(
        sa.text(
            "SELECT images.name FROM image_fts JOIN images ON images.id = image_fts.rowid "
            "WHERE image_fts MATCH :q ORDER BY images.name"
        ),
        {"q": word},
    )
    return [name for (name,) in rows]


def test_images_keep_their_triggers_and_take_linked_files(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "027")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO variant_groups (id, base_name, image_count) VALUES (1, 'Forest', 0)"
            )
        )
        _insert_image(conn, "Forest Day", 1, storage_key="day.png")

    command.upgrade(cfg, "028")

    with engine.begin() as conn:
        # The rows and the full-text index came through the rebuild
        assert _search(conn, "forest") == ["Forest Day"]
        conn.execute(
            sa.text(
                "INSERT INTO library_sources (id, kind, location, state) "
                "VALUES (1, 'folder', '/maps', 'online')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO source_files (id, source_id, rel_key, size, mtime_ns, state) "
                "VALUES (1, 1, 'A/night.png', 1, 1, 'image')"
            )
        )
        # A linked image: no storage key
        _insert_image(conn, "Forest Night", 1, source_file_id=1)
        # The triggers still run: full-text search and the group's image count
        assert _search(conn, "night") == ["Forest Night"]
        count = conn.execute(sa.text("SELECT image_count FROM variant_groups WHERE id = 1"))
        assert count.scalar() == 2
        conn.execute(sa.text("DELETE FROM images WHERE name = 'Forest Day'"))
        assert _search(conn, "day") == []
        count = conn.execute(sa.text("SELECT image_count FROM variant_groups WHERE id = 1"))
        assert count.scalar() == 1

    # An image with neither is refused, as is a second image for one file
    for extra in ({}, {"source_file_id": 1}):
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            _insert_image(conn, "Orphan", 1, **extra)

    command.downgrade(cfg, "027")
    with engine.connect() as conn:
        assert _search(conn, "forest") == []  # the linked image went with the downgrade
        tables = sa.inspect(conn).get_table_names()
        assert "source_files" not in tables and "library_sources" not in tables
    engine.dispose()
