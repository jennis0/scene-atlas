"""Store CIELAB per colour row so colour search runs in SQL.

Adds ``colors.lab_l``, ``lab_a`` and ``lab_b`` (CIELAB, D65), backfills them
from ``color_hex``, makes them NOT NULL, and adds ``ix_colors_lab`` for the
search's bounding-box prefilter. This replaces the in-memory colour index.

The ``color_distance_threshold`` setting changes units from cylindrical-HSL
distance to CIE76 delta E. Comparing match sets on dominant colours extracted
from 3,000 real maps, old thresholds of 0.1 / 0.2 / 0.35 / 0.5 give about the
same number of matches as delta E 7 / 15 / 25 / 38, so the old default maps to
25 and custom values scale linearly by the same ratio (clamped to 0-100).

The conversion is a copy of ``backend.app.colorspace.hex_to_lab``: migrations
must not import app code, which keeps changing after they are written.

Revision ID: 024
Revises: 023
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

_CHUNK = 5000
_OLD_DEFAULT = 0.35
_NEW_DEFAULT = 25.0
_MAX_DELTA_E = 100.0
_INDEX_COLUMNS = ["lab_l", "lab_a", "lab_b", "image_id"]


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116


def hex_to_lab(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    r, g, b = (_linear(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _backfill(conn) -> None:
    last_id = 0
    while True:
        rows = conn.execute(
            sa.text("SELECT id, color_hex FROM colors WHERE id > :last ORDER BY id LIMIT :n"),
            {"last": last_id, "n": _CHUNK},
        ).fetchall()
        if not rows:
            return
        conn.execute(
            sa.text("UPDATE colors SET lab_l = :l, lab_a = :a, lab_b = :b WHERE id = :id"),
            [
                dict(zip(("l", "a", "b"), hex_to_lab(hex_val), strict=True), id=row_id)
                for row_id, hex_val in rows
            ],
        )
        last_id = rows[-1][0]


def _rescale_threshold(
    conn, factor: float, old_default: float, new_default: float, cap: float
) -> None:
    row = conn.execute(
        sa.text("SELECT value_json FROM app_settings WHERE key = 'color_distance_threshold'")
    ).fetchone()
    if row is None or row[0] is None:
        return
    try:
        value = float(json.loads(row[0]))
    except (TypeError, ValueError):
        return
    if abs(value - old_default) < 1e-9:
        new = new_default
    else:
        new = min(max(round(value * factor, 3), 0.0), cap)
    conn.execute(
        sa.text("UPDATE app_settings SET value_json = :v WHERE key = 'color_distance_threshold'"),
        {"v": json.dumps(new)},
    )


def upgrade() -> None:
    for column in ("lab_l", "lab_a", "lab_b"):
        op.add_column("colors", sa.Column(column, sa.Float(), nullable=True))
    conn = op.get_bind()
    _backfill(conn)
    with op.batch_alter_table("colors") as batch:
        for column in ("lab_l", "lab_a", "lab_b"):
            batch.alter_column(column, existing_type=sa.Float(), nullable=False)
    op.create_index("ix_colors_lab", "colors", _INDEX_COLUMNS)
    _rescale_threshold(conn, _NEW_DEFAULT / _OLD_DEFAULT, _OLD_DEFAULT, _NEW_DEFAULT, _MAX_DELTA_E)


def downgrade() -> None:
    conn = op.get_bind()
    _rescale_threshold(conn, _OLD_DEFAULT / _NEW_DEFAULT, _NEW_DEFAULT, _OLD_DEFAULT, float("inf"))
    op.drop_index("ix_colors_lab", table_name="colors")
    with op.batch_alter_table("colors") as batch:
        for column in ("lab_l", "lab_a", "lab_b"):
            batch.drop_column(column)
