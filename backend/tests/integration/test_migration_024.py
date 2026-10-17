"""Migration 024 backfills LAB per colour row and moves the colour threshold to delta E."""

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from backend.app.colorspace import hex_to_lab
from backend.app.models.schemas import AppSettings

ROOT = Path(__file__).resolve().parents[3]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.config_file_name = None  # don't let Alembic reconfigure logging
    return cfg


def _at_023(tmp_path, threshold: float | None):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "023")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO images (id, filename, storage_key, name) VALUES (1, 'a', 'a', 'a')"
            )
        )
        if threshold is not None:
            conn.execute(
                sa.text(
                    "INSERT INTO app_settings (key, value_json) "
                    "VALUES ('color_distance_threshold', :v)"
                ),
                {"v": json.dumps(threshold)},
            )
    return cfg, engine


def _threshold(engine) -> float:
    with engine.connect() as conn:
        value = conn.execute(
            sa.text("SELECT value_json FROM app_settings WHERE key = 'color_distance_threshold'")
        ).scalar_one()
    return json.loads(value)


def test_backfills_every_row_across_chunks(tmp_path):
    cfg, engine = _at_023(tmp_path, None)
    hexes = [f"#{(i * 2654435761) % (1 << 24):06x}" for i in range(5003)]  # > one chunk
    hexes[:3] = ["#000000", "#ffffff", "#FF0000"]
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO colors (image_id, color_hex, color_order) VALUES (1, :h, 1)"),
            [{"h": h} for h in hexes],
        )

    command.upgrade(cfg, "024")

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT color_hex, lab_l, lab_a, lab_b FROM colors ORDER BY id")
        ).all()
        index_columns = [
            r[2] for r in conn.execute(sa.text("PRAGMA index_info('ix_colors_lab')")).all()
        ]
    assert len(rows) == len(hexes)
    for hex_val, *lab in rows:
        assert tuple(lab) == pytest.approx(hex_to_lab(hex_val), abs=1e-9)
    assert index_columns == ["lab_l", "lab_a", "lab_b", "image_id"]

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO colors (image_id, color_hex) VALUES (1, '#123456')"))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (0.35, AppSettings().color_distance_threshold),
        (0.7, AppSettings().color_distance_threshold * 2),
        (0.1, AppSettings().color_distance_threshold * 0.1 / 0.35),
    ],
)
def test_threshold_moves_to_delta_e(tmp_path, old, new):
    cfg, engine = _at_023(tmp_path, old)
    command.upgrade(cfg, "024")
    assert _threshold(engine) == pytest.approx(new, abs=1e-3)

    command.downgrade(cfg, "023")
    assert _threshold(engine) == pytest.approx(old, abs=1e-3)
    with engine.connect() as conn:
        columns = {r[1] for r in conn.execute(sa.text("PRAGMA table_info('colors')")).all()}
    assert not columns & {"lab_l", "lab_a", "lab_b"}


@pytest.mark.parametrize(("old", "new"), [(2.0, 100.0), (-0.1, 0.0)])
def test_out_of_range_threshold_clamped(tmp_path, old, new):
    cfg, engine = _at_023(tmp_path, old)
    command.upgrade(cfg, "024")
    assert _threshold(engine) == new


def test_missing_threshold_setting_left_alone(tmp_path):
    cfg, engine = _at_023(tmp_path, None)
    command.upgrade(cfg, "024")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM app_settings")).scalar_one() == 0
