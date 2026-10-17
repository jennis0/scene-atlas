"""Migration 026 settles existing file-name grid sizes against their image."""

import importlib.util
import itertools
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from backend.app.services.image_parser import ImageParser
from backend.pipeline.filename_grid import filename_grid_counts

ROOT = Path(__file__).resolve().parents[3]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.config_file_name = None  # don't let Alembic reconfigure logging
    return cfg


def test_file_name_grids_are_settled_against_the_image(tmp_path):
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
        "glued_digit": ("filename", None, 630, 50, 4200, 5999),
        "glued_and_swapped": ("filename", None, 218, 27, 3769, 2594),
        "real_three_digit": ("filename", None, 100, 100, 7000, 7000),
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
        "glued_digit": (30, 50),
        "glued_and_swapped": (27, 18),
        "real_three_digit": (100, 100),
    }


def test_migration_copy_matches_ingest():
    """The migration copies the parser and ingest rules; they must agree."""
    spec = importlib.util.spec_from_file_location(
        "migration_026", ROOT / "backend/alembic/versions/026_settle_filename_grids.py"
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    parser = ImageParser(tag_categories=[])

    sizes = [(30, 20), (20, 30), (630, 50), (25, 201), (218, 27), (100, 100), (123, 456)]
    images = [(3000, 2000), (2000, 3000), (3000, 2980), (4200, 5999), (5000, 4000), (2594, 3769)]
    for (gw, gh), (width, height) in itertools.product(sizes, images):
        parsed = parser.parse(f"author/group/Map_{gw}x{gh}.jpg")
        expected = filename_grid_counts(parsed, width, height)
        assert migration.settle(gw, gh, width, height) == (
            expected["grid_width"],
            expected["grid_height"],
        ), (gw, gh, width, height)
