"""Settle existing grid sizes taken from file names against their image.

Ingest stored a file name's NxM as read. ``grid_width`` is the column count, but:

- names disagree on whether "30x20" means columns x rows or rows x columns, so a
  portrait map named "30x20" was stored as 30 columns of very tall cells;
- a digit from the name can be glued on: "Destroyed630x50" is variant 6 at 30x50.

Ingest now settles both once the pixel size is known
(``backend.pipeline.filename_grid``); this applies the same rules to existing rows.
They are copied here because migrations must not import app code. Stored sizes are
still in name order, which the glued-digit rule needs.

Only exact file-name sizes change (``grid_source = 'filename'`` with no confidence).
Detected sizes are measured per axis, and grids set by hand are the user's.

The downgrade is a no-op: which rows changed is not recorded.

Revision ID: 026
Revises: 025
"""

import math

import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"

_SQUARE_TOLERANCE = 50
_LITERAL_MAX_SKEW = math.log(1.5)
_ALTERNATIVE_MAX_SKEW = math.log(1.25)


def _orient(gw: int, gh: int, width: int, height: int) -> tuple[int, int]:
    if abs(width - height) * _SQUARE_TOLERANCE <= max(width, height):
        return gw, gh
    if (gw > gh) != (width > height):
        return gh, gw
    return gw, gh


def _skew(size: tuple[int, int], width: int, height: int) -> float:
    return abs(math.log((width / size[0]) / (height / size[1])))


def _alternatives(gw: int, gh: int) -> list[tuple[int, int]]:
    left, right = str(gw), str(gh)
    lefts = [left] + ([left[1:]] if len(left) == 3 and left[1] != "0" else [])
    rights = [right] + ([right[:2]] if len(right) == 3 else [])
    return [(int(w), int(h)) for w in lefts for h in rights if (w, h) != (left, right)]


def settle(gw: int, gh: int, width: int, height: int) -> tuple[int, int]:
    chosen = _orient(gw, gh, width, height)
    oriented = [_orient(w, h, width, height) for w, h in _alternatives(gw, gh)]
    best = min(oriented, key=lambda size: _skew(size, width, height), default=chosen)
    if (
        _skew(chosen, width, height) > _LITERAL_MAX_SKEW
        and _skew(best, width, height) <= _ALTERNATIVE_MAX_SKEW
    ):
        chosen = best
    return chosen


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, grid_width, grid_height, width, height FROM images"
            " WHERE grid_source = 'filename' AND grid_confidence IS NULL"
            " AND grid_width > 0 AND grid_height > 0 AND width > 0 AND height > 0"
        )
    ).all()
    updates = []
    for image_id, gw, gh, width, height in rows:
        settled = settle(gw, gh, width, height)
        if settled != (gw, gh):
            updates.append({"id": image_id, "w": settled[0], "h": settled[1]})
    if updates:
        conn.execute(
            sa.text("UPDATE images SET grid_width = :w, grid_height = :h WHERE id = :id"),
            updates,
        )


def downgrade():
    pass
