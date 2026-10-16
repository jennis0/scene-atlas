"""Migration 022 labels each existing image's grid source from what is known."""

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


def test_existing_rows_get_a_grid_source(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "021")
    engine = sa.create_engine(url)
    rows = {
        "detected": {"gridded": 1, "grid_width": 30, "grid_confidence": 0.9},
        "named": {"gridded": 1, "grid_width": 30, "grid_confidence": None},
        "named_no_grid": {"gridded": 0, "grid_width": None, "grid_confidence": None},
        "unknown": {"gridded": None, "grid_width": None, "grid_confidence": None},
    }
    with engine.begin() as conn:
        for name, grid in rows.items():
            conn.execute(
                sa.text(
                    "INSERT INTO images (filename, storage_key, name, gridded, grid_width,"
                    " grid_confidence) VALUES (:f, :k, :n, :g, :w, :c)"
                ),
                {
                    "f": f"{name}.jpg",
                    "k": f"{name}.jpg",
                    "n": name,
                    "g": grid["gridded"],
                    "w": grid["grid_width"],
                    "c": grid["grid_confidence"],
                },
            )

    command.upgrade(cfg, "022")

    with engine.connect() as conn:
        sources = dict(conn.execute(sa.text("SELECT name, grid_source FROM images")).all())
    assert sources == {
        "detected": "detector",
        "named": "filename",
        "named_no_grid": "filename",
        "unknown": None,
    }
