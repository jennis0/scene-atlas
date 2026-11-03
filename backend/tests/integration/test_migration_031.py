"""Migration 031 copies content_hash into a missing stored_hash (and nothing else), and gives
any group without a uid one."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def test_upgrade_copies_content_hash_where_stored_hash_is_missing(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.config_file_name = None
    command.upgrade(cfg, "030")
    engine = sa.create_engine(url)
    rows = [
        ("a", "aa", None),  # copied
        ("b", "bb", "cc"),  # converted at import: kept
        ("c", None, None),  # neither: left for the startup job
    ]
    with engine.begin() as conn:
        for name, content, stored in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO images (filename, storage_key, content_hash, stored_hash) "
                    "VALUES (:n, :n, :c, :s)"
                ),
                {"n": name, "c": content, "s": stored},
            )
        conn.execute(sa.text("INSERT INTO variant_groups (base_name, image_count) VALUES ('G', 0)"))

    command.upgrade(cfg, "031")

    with engine.begin() as conn:
        found = conn.execute(sa.text("SELECT filename, stored_hash FROM images ORDER BY filename"))
        assert list(found) == [("a", "aa"), ("b", "cc"), ("c", None)]
        uid = conn.execute(sa.text("SELECT uid FROM variant_groups")).scalar()
        assert uid is not None and len(uid) == 32
