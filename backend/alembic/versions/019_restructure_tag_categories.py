"""Restructure tag categories for expanded vocabulary.

Renames: terrain -> environment, quality -> style
Creates: features (split from terrain)
Drops: floor (interior moves to environment)
Moves feature-type tags from environment to features.

Revision ID: 019
Revises: 018
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"

# Tags that should live in "features" rather than "environment" (formerly "terrain")
FEATURE_VALUES = {
    "bridge",
    "camp",
    "temple",
    "dungeon",
    "road",
    "tavern",
    "castle",
    "tower",
    "ruins",
    "rock",
    "tree",
}


def upgrade():
    conn = op.get_bind()

    # Check if migration already ran or DB is fresh (no old categories to migrate)
    has_environment = conn.execute(
        sa.text("SELECT name FROM tag_categories WHERE name = 'environment'")
    ).fetchone()
    if has_environment:
        return

    has_terrain = conn.execute(
        sa.text("SELECT name FROM tag_categories WHERE name = 'terrain'")
    ).fetchone()
    if not has_terrain:
        # Fresh DB — nothing to migrate, seeder will handle population
        return

    # 1. Rename "quality" -> "style"
    conn.execute(sa.text("UPDATE tag_categories SET name = 'style' WHERE name = 'quality'"))
    conn.execute(sa.text("UPDATE tags SET category = 'style' WHERE category = 'quality'"))

    # 2. Rename "terrain" -> "environment"
    conn.execute(sa.text("UPDATE tag_categories SET name = 'environment' WHERE name = 'terrain'"))
    conn.execute(sa.text("UPDATE tags SET category = 'environment' WHERE category = 'terrain'"))

    # 3. Create "features" category
    conn.execute(
        sa.text(
            "INSERT INTO tag_categories (name, description, color, icon, display_order) "
            "VALUES ('features', 'Specific structures and landmarks', 'stone', "
            "'castle', 4)"
        )
    )

    # 4. Move feature-type tags from environment to features
    placeholders = ", ".join(f"'{v}'" for v in FEATURE_VALUES)
    conn.execute(
        sa.text(
            f"UPDATE tags SET category = 'features' "
            f"WHERE category = 'environment' AND value IN ({placeholders})"
        )
    )

    # 5. Update common_values on environment to remove feature values
    row = conn.execute(
        sa.text("SELECT common_values FROM tag_categories WHERE name = 'environment'")
    ).fetchone()
    if row and row[0]:
        values = json.loads(row[0])
        env_values = []
        feature_values = []
        for v in values:
            canonical = v if isinstance(v, str) else v["value"]
            if canonical in FEATURE_VALUES:
                feature_values.append(v)
            else:
                env_values.append(v)
        conn.execute(
            sa.text("UPDATE tag_categories SET common_values = :cv WHERE name = 'environment'"),
            {"cv": json.dumps(env_values)},
        )
        conn.execute(
            sa.text("UPDATE tag_categories SET common_values = :cv WHERE name = 'features'"),
            {"cv": json.dumps(feature_values)},
        )

    # 6. Handle "floor" category: move interior to environment, drop the rest
    conn.execute(
        sa.text(
            "UPDATE tags SET category = 'environment' "
            "WHERE category = 'floor' AND value = 'interior'"
        )
    )
    conn.execute(sa.text("DELETE FROM tags WHERE category = 'floor'"))
    conn.execute(sa.text("DELETE FROM tag_categories WHERE name = 'floor'"))

    # 7. Update display_order for new category arrangement
    order = [
        "lighting",
        "season",
        "weather",
        "environment",
        "features",
        "state",
        "theme",
        "population",
        "perspective",
        "style",
    ]
    for i, name in enumerate(order):
        conn.execute(
            sa.text("UPDATE tag_categories SET display_order = :order WHERE name = :name"),
            {"order": i, "name": name},
        )


def downgrade():
    conn = op.get_bind()

    # Reverse: merge features back into terrain, rename back
    conn.execute(sa.text("UPDATE tags SET category = 'terrain' WHERE category = 'features'"))
    conn.execute(sa.text("UPDATE tags SET category = 'terrain' WHERE category = 'environment'"))
    conn.execute(sa.text("UPDATE tag_categories SET name = 'terrain' WHERE name = 'environment'"))
    conn.execute(sa.text("DELETE FROM tag_categories WHERE name = 'features'"))

    conn.execute(sa.text("UPDATE tag_categories SET name = 'quality' WHERE name = 'style'"))
    conn.execute(sa.text("UPDATE tags SET category = 'quality' WHERE category = 'style'"))

    # Re-create floor category
    conn.execute(
        sa.text(
            "INSERT INTO tag_categories (name, description, color, display_order, "
            "common_values) VALUES ('floor', 'Building level or floor', 'stone', 7, "
            '\'["roof", "basement", "interior", '
            '{"value": "ground", "aliases": ["ground floor"]}]\')'
        )
    )
    conn.execute(
        sa.text(
            "UPDATE tags SET category = 'floor' "
            "WHERE category = 'environment' AND value = 'interior'"
        )
    )
