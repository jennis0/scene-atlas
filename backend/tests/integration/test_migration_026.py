"""Migration 026 orients existing file-name grid sizes to match their image."""

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


def test_file_name_grids_are_oriented_to_the_image(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "025")
    engine = sa.create_engine(url)
    # name: (grid_source, grid_confidence, grid_width, grid_height, width, height)
    rows = {
        "swapped": ("filename", None, 20, 30, 3000, 2000),
        "portrait": ("filename", None, 30, 20, 2000, 3000),
        "matching": ("filename", None, 30, 20, 3000, 2000),
        "square_image": ("filename", None, 20, 30, 3000, 3000),
        "near_square": ("filename", None, 20, 30, 3000, 2980),
        "detected": ("filename", 0.9, 20, 30, 3000, 2000),
        "detector": ("detector", 0.9, 20, 30, 3000, 2000),
        "user": ("user", None, 20, 30, 3000, 2000),
        "no_dimensions": ("filename", None, 20, 30, None, None),
    }
    with engine.begin() as conn:
        for name, (source, conf, gw, gh, w, h) in rows.items():
            conn.execute(
                sa.text(
                    "INSERT INTO images (filename, storage_key, name, gridded, grid_source,"
                    " grid_confidence, grid_width, grid_height, width, height)"
                    " VALUES (:n, :n, :n, 1, :s, :c, :gw, :gh, :w, :h)"
                ),
                {"n": name, "s": source, "c": conf, "gw": gw, "gh": gh, "w": w, "h": h},
            )

    command.upgrade(cfg, "026")

    with engine.connect() as conn:
        result = {
            name: (gw, gh)
            for name, gw, gh in conn.execute(
                sa.text("SELECT name, grid_width, grid_height FROM images")
            )
        }
    assert result == {
        "swapped": (30, 20),
        "portrait": (20, 30),
        "matching": (30, 20),
        "square_image": (20, 30),
        "near_square": (20, 30),
        "detected": (20, 30),
        "detector": (20, 30),
        "user": (20, 30),
        "no_dimensions": (20, 30),
    }
