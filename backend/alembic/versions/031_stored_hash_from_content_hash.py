"""Fill ``images.stored_hash`` for images from before it existed.

Every import since migration 020 records ``stored_hash`` (the hash of the stored file).
Stored-format conversion arrived with the same change, so an image without one was
never converted: its stored file is the original, whose hash is ``content_hash``. Copying
it is exact and reads no file. Images with neither are hashed by
``pipeline.backfill_content_hash.backfill_stored_hash`` at startup.

Also gives a uid to any group without one.

Revision ID: 031
Revises: 030
"""

from alembic import op

revision = "031"
down_revision = "030"


def upgrade():
    op.execute(
        "UPDATE images SET stored_hash = content_hash "
        "WHERE stored_hash IS NULL AND content_hash IS NOT NULL"
    )
    # Every group has a uid (030 and the model set it); fill any a raw insert left out,
    # since an export can't write a group without one.
    op.execute("UPDATE variant_groups SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL")


def downgrade():
    # Data only, and harmless to keep: nothing tells the copied hashes apart.
    pass
