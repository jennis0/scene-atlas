"""SQLAlchemy database models for Scene Atlas."""

import json
import logging
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class Image(Base):
    """Main image table."""

    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False, index=True)  # Original filename for display
    storage_key = Column(
        String, nullable=False, index=True
    )  # Key into ImageStore (e.g., "a1b2c3d4.jpg")
    name = Column(String, index=True)  # Inferred base name / variant group name
    author = Column(String, index=True)
    group_id = Column("variant_group_id", Integer, ForeignKey("variant_groups.id"), nullable=True)

    # Image properties
    width = Column(Integer)
    height = Column(Integer)
    file_size = Column(Integer)  # In bytes
    gridded = Column(Boolean, nullable=True)  # True=gridded, False=gridless, None=unknown
    grid_width = Column(Integer, nullable=True)  # Grid tile count horizontal (e.g. 30)
    grid_height = Column(Integer, nullable=True)  # Grid tile count vertical (e.g. 45)
    grid_type = Column(String, nullable=True)  # "square" | "hex" | None
    grid_confidence = Column(Float, nullable=True)  # 0.0-1.0, None = filename-detected
    subgroup = Column("sub_variant", String, nullable=True)  # Subgroup path (e.g. "MA / No Grid")
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 hex digest
    search_text = Column(Text, nullable=True)  # Pre-tokenized text for FTS5 (CamelCase-split)
    media_type = Column(String, nullable=True, default="image")  # "image" or "video"
    image_type = Column(String, nullable=True, default="battlemap")  # "battlemap" or "scene"

    # Storage keys (resolved via ImageStore at runtime)
    thumbnail_key = Column(String)  # Key into thumbnail store (e.g., "a1b2c3d4_400x400.jpg")

    # Metadata
    needs_review = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tags = relationship("Tag", back_populates="image", cascade="all, delete-orphan")
    colors = relationship("Color", back_populates="image", cascade="all, delete-orphan")
    group = relationship("ImageGroup", back_populates="images", foreign_keys="[Image.group_id]")

    @property
    def group_name(self) -> str | None:
        return self.group.base_name if self.group else None

    @property
    def group_image_count(self) -> int | None:
        return len(self.group.images) if self.group else None

    def __repr__(self):
        return f"<Image(id={self.id}, name='{self.name}', filename='{self.filename}')>"


class ImageGroup(Base):
    """Groups related scenes together."""

    __tablename__ = "variant_groups"

    id = Column(Integer, primary_key=True, index=True)
    base_name = Column(String, nullable=False, index=True)
    author = Column(String, index=True)
    primary_image_id = Column(Integer, ForeignKey("images.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    images = relationship("Image", back_populates="group", foreign_keys="[Image.group_id]")

    def __repr__(self):
        return f"<ImageGroup(id={self.id}, base_name='{self.base_name}')>"


class Tag(Base):
    """Tag system for multidimensional variant categorization."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)
    category = Column(String, nullable=False, index=True)  # e.g., 'grid', 'season', 'lighting'
    value = Column(String, nullable=False, index=True)  # e.g., 'gridded', 'winter', 'night'
    confidence = Column(Float, default=1.0)  # 0.0-1.0 for auto-inferred tags
    source = Column(String, default="manual")  # 'auto' or 'manual'
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    image = relationship("Image", back_populates="tags")

    def __repr__(self):
        return (
            f"<Tag(category='{self.category}', value='{self.value}', confidence={self.confidence})>"
        )


class TagCategory(Base):
    """Defines available tag categories and their common values."""

    __tablename__ = "tag_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text)
    common_values = Column(Text)  # JSON array of typical values
    color = Column(String, nullable=True)  # Tailwind color preset name, e.g. "amber"
    icon = Column(String, nullable=True)  # Lucide icon name, e.g. "leaf"
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TagCategory(name='{self.name}')>"


class Color(Base):
    """Dominant colors extracted from images."""

    __tablename__ = "colors"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)
    color_hex = Column(String(7), nullable=False, index=True)  # e.g., '#1a2b3c'
    percentage = Column(Float)  # 0.0-100.0
    color_order = Column(Integer)  # 1-5 for dominant colors

    # Relationships
    image = relationship("Image", back_populates="colors")

    def __repr__(self):
        return f"<Color(hex='{self.color_hex}', percentage={self.percentage})>"


class ImportJob(Base):
    """Tracks image import jobs (one per upload session).

    Represents the full editing session, from upload through group confirmation.
    Individual group processing is tracked by ImportGroupJob children.
    """

    __tablename__ = "import_jobs"

    id = Column(String, primary_key=True)  # UUID
    status = Column(String, nullable=False, default="staging")
    # status values: staging, active, completed, failed, cancelled, expired
    source_label = Column(String, nullable=True)  # Display label for import tray
    total_files = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    # JSON: [{group_name, author, file_count}, ...] — analysis output for pending count tracking
    analysis_result = Column(Text, nullable=True)
    # True when confirm-all was used — allows auto-completion when all groups finish
    all_confirmed = Column(Boolean, default=False)

    # Relationships
    groups = relationship("ImportGroupJob", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ImportJob(id='{self.id}', status='{self.status}')>"


class AppSetting(Base):
    """Key-value store for DB-backed application settings (feature flags, tuning params)."""

    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=True)  # JSON-encoded value
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AppSetting(key='{self.key}', value_json='{self.value_json}')>"


class ImportGroupJob(Base):
    """Tracks progress of a single group within an import job."""

    __tablename__ = "import_group_jobs"

    id = Column(String, primary_key=True)  # UUID hex
    job_id = Column(String, ForeignKey("import_jobs.id"), nullable=False, index=True)
    group_name = Column("variant_group_name", String, nullable=False)
    author = Column(String, nullable=True)
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    failed_files = Column(Integer, default=0)
    status = Column(String, nullable=False, default="running")
    # status values: running, completed, failed, cancelled
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    # Set once the group finishes so the frontend can link back to the created ImageGroup
    created_group_id = Column(Integer, nullable=True)

    # Relationships
    job = relationship("ImportJob", back_populates="groups")

    def __repr__(self):
        return (
            f"<ImportGroupJob(id='{self.id}', group='{self.group_name}', status='{self.status}')>"
        )


# Database setup utilities
def get_engine(database_url: str = "sqlite:///./data/battlemap.db"):
    """Create database engine."""
    return create_engine(
        database_url, connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
    )


def get_session_local(engine):
    """Create session factory."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_images_content_hash(engine):
    """Add content_hash column and remove UNIQUE constraint from storage_key.

    SQLite cannot ALTER TABLE to drop constraints, so we recreate the table
    when the migration is needed. This is idempotent — it checks whether
    content_hash already exists before doing anything.
    """
    with engine.connect() as conn:
        # Check if migration is needed
        cols = conn.execute(text("PRAGMA table_info(images)")).fetchall()
        col_names = {row[1] for row in cols}

        if "content_hash" in col_names:
            return  # Already migrated

        logger.info("Migrating images table: adding content_hash, removing UNIQUE on storage_key")

        # Drop FTS triggers first (they reference the images table)
        conn.execute(text("DROP TRIGGER IF EXISTS image_fts_ai"))
        conn.execute(text("DROP TRIGGER IF EXISTS image_fts_ad"))
        conn.execute(text("DROP TRIGGER IF EXISTS image_fts_au"))
        # Drop FTS table so it gets recreated fresh by init_db
        conn.execute(text("DROP TABLE IF EXISTS image_fts"))

        # Recreate images table without UNIQUE on storage_key, with content_hash
        conn.execute(
            text("""
            CREATE TABLE images_new (
                id INTEGER PRIMARY KEY,
                filename VARCHAR NOT NULL,
                storage_key VARCHAR NOT NULL,
                name VARCHAR,
                author VARCHAR,
                variant_group_id INTEGER REFERENCES variant_groups(id),
                width INTEGER,
                height INTEGER,
                file_size INTEGER,
                gridded BOOLEAN,
                grid_width INTEGER,
                grid_height INTEGER,
                sub_variant VARCHAR,
                content_hash VARCHAR(64),
                thumbnail_key VARCHAR,
                needs_review BOOLEAN DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME
            )
        """)
        )

        conn.execute(
            text("""
            INSERT INTO images_new (
                id, filename, storage_key, name, author, variant_group_id,
                width, height, file_size, gridded, grid_width, grid_height,
                sub_variant, thumbnail_key, needs_review, created_at, updated_at
            )
            SELECT
                id, filename, storage_key, name, author, variant_group_id,
                width, height, file_size, gridded, grid_width, grid_height,
                sub_variant, thumbnail_key, needs_review, created_at, updated_at
            FROM images
        """)
        )

        conn.execute(text("DROP TABLE images"))
        conn.execute(text("ALTER TABLE images_new RENAME TO images"))

        # Recreate indexes
        conn.execute(text("CREATE INDEX ix_images_id ON images (id)"))
        conn.execute(text("CREATE INDEX ix_images_filename ON images (filename)"))
        conn.execute(text("CREATE INDEX ix_images_storage_key ON images (storage_key)"))
        conn.execute(text("CREATE INDEX ix_images_name ON images (name)"))
        conn.execute(text("CREATE INDEX ix_images_author ON images (author)"))
        conn.execute(text("CREATE INDEX ix_images_needs_review ON images (needs_review)"))
        conn.execute(text("CREATE INDEX ix_images_content_hash ON images (content_hash)"))

        conn.commit()
        logger.info("Images table migration complete")


def init_db(engine):
    """Initialize / migrate the database using Alembic.

    Behaviour:
    - **Fresh database** (no tables): runs all Alembic migrations from scratch.
    - **Pre-Alembic database** (tables exist, no ``alembic_version`` table):
      the existing schema is already in the target state (all prior hand-rolled
      migrations have already run at startup), so we stamp at ``head`` to bring
      it under Alembic management without re-running any DDL.
    - **Alembic-managed database**: applies any pending migrations (upgrade head).
    """
    # Locate alembic.ini — path differs between normal runtime and frozen binary.
    # In a PyInstaller --onedir binary sys._MEIPASS is the _internal/ directory
    # where bundled data files (including alembic.ini) are extracted.
    import sys as _sys
    from pathlib import Path as _Path

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        # Frozen PyInstaller binary: alembic.ini and backend/alembic/ are bundled
        # into sys._MEIPASS (_internal/).  Alembic resolves script_location via
        # os.path.abspath() (relative to CWD, not the config file), so we must
        # override it with the absolute _MEIPASS path after loading the config.
        alembic_ini = _Path(_sys._MEIPASS) / "alembic.ini"
        alembic_cfg = AlembicConfig(str(alembic_ini))
        alembic_cfg.set_main_option(
            "script_location",
            str(_Path(_sys._MEIPASS) / "backend" / "alembic"),
        )
    else:
        # Normal dev runtime: 4 levels up from backend/app/models/database.py
        alembic_ini = _Path(__file__).parent.parent.parent.parent / "alembic.ini"
        alembic_cfg = AlembicConfig(str(alembic_ini))
    # Always override the URL to use this engine's actual database path
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))

    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current_rev = context.get_current_revision()

    if current_rev is None:
        inspector = inspect(engine)
        if "images" in inspector.get_table_names():
            # Pre-Alembic database: schema is already up to date.
            # Stamp at head to bring it under Alembic management.
            logger.info("Stamping pre-Alembic database at head revision")
            command.stamp(alembic_cfg, "head")
        else:
            # Fresh database: create everything via migrations.
            logger.info("Running Alembic migrations on fresh database")
            command.upgrade(alembic_cfg, "head")
    else:
        # Already Alembic-managed: apply any pending migrations.
        logger.info(f"Running Alembic upgrade (current: {current_rev})")
        command.upgrade(alembic_cfg, "head")


def seed_tag_categories(session):
    """Seed initial tag categories with vocabulary for auto-tagging.

    Only runs when the tag_categories table is completely empty (first boot).
    Once categories exist, this is a no-op so user edits are preserved.

    Each common_values entry can be:
    - A plain string: used as both lookup word and canonical value
    - An object: {"value": "rain", "aliases": ["rainy", "raining"]}
      Aliases are alternative words that map to the canonical value.

    The ImageParser loads these to build its tag vocabulary.
    """
    existing_count = session.query(TagCategory).count()
    if existing_count > 0:
        return

    categories = [
        {
            "name": "lighting",
            "description": "Time of day and lighting conditions",
            "color": "amber",
            "display_order": 0,
            "common_values": json.dumps(
                [
                    "night",
                    "day",
                    "dusk",
                    "dawn",
                    "twilight",
                    {"value": "dark", "aliases": ["darkness"]},
                    "sunset",
                    "lit",
                    "unlit",
                ]
            ),
        },
        {
            "name": "season",
            "description": "Seasonal variations",
            "color": "orange",
            "display_order": 1,
            "common_values": json.dumps(
                [
                    "spring",
                    "summer",
                    "winter",
                    {"value": "autumn", "aliases": ["fall"]},
                ]
            ),
        },
        {
            "name": "weather",
            "description": "Weather conditions",
            "color": "sky",
            "display_order": 2,
            "common_values": json.dumps(
                [
                    {"value": "rain", "aliases": ["rainy", "raining"]},
                    {"value": "snow", "aliases": ["snowy", "snowing"]},
                    {"value": "fog", "aliases": ["foggy"]},
                    {"value": "storm", "aliases": ["stormy"]},
                    {"value": "mist", "aliases": ["misty"]},
                ]
            ),
        },
        {
            "name": "state",
            "description": "Condition or state of the map",
            "color": "red",
            "display_order": 3,
            "common_values": json.dumps(
                [
                    {"value": "bloody", "aliases": ["blood", "bloodbath"]},
                    {"value": "ruined", "aliases": ["ruins", "ruin"]},
                    {"value": "burned", "aliases": ["burnt", "fire"]},
                    "abandoned",
                    "overgrown",
                    "flooded",
                    {"value": "frozen", "aliases": ["icy"]},
                    "polluted",
                ]
            ),
        },
        {
            "name": "theme",
            "description": "Thematic variations",
            "color": "purple",
            "display_order": 4,
            "common_values": json.dumps(
                [
                    {"value": "fey", "aliases": ["feywild"]},
                    {"value": "shadow", "aliases": ["shadowfell"]},
                    "underdark",
                    "pirate",
                    "astral",
                    "ethereal",
                ]
            ),
        },
        {
            "name": "population",
            "description": "Occupancy state",
            "color": "cyan",
            "display_order": 5,
            "common_values": json.dumps(
                [
                    {"value": "empty", "aliases": ["propless"]},
                    "furnished",
                    "populated",
                    "battle",
                ]
            ),
        },
        {
            "name": "terrain",
            "description": "Terrain and environment type",
            "color": "emerald",
            "display_order": 6,
            "common_values": json.dumps(
                [
                    "forest",
                    "cave",
                    "river",
                    "bridge",
                    "camp",
                    "temple",
                    "village",
                    "island",
                    "dungeon",
                    "road",
                    "mountain",
                    "swamp",
                    "ocean",
                    "tavern",
                    "castle",
                    "rock",
                    "tree",
                    "desert",
                    "lake",
                    "tower",
                    "ruins",
                ]
            ),
        },
        {
            "name": "floor",
            "description": "Building level or floor",
            "color": "stone",
            "display_order": 7,
            "common_values": json.dumps(
                [
                    "roof",
                    "basement",
                    "interior",
                    {"value": "ground", "aliases": ["ground floor"]},
                ]
            ),
        },
        {
            "name": "perspective",
            "description": "Viewing angle",
            "color": "violet",
            "display_order": 8,
            "common_values": json.dumps(["top-down", "isometric", "side-view"]),
        },
        {
            "name": "quality",
            "description": "Artistic style and quality",
            "color": "rose",
            "display_order": 9,
            "common_values": json.dumps(["line-art", "colored", "rendered", "sketch"]),
        },
    ]

    for cat_data in categories:
        session.add(TagCategory(**cat_data))

    session.commit()


def seed_default_settings(session):
    """Seed default app settings into the DB on first boot.

    Only runs when the app_settings table is completely empty.
    Once any setting row exists, this is a no-op so user-edited values are preserved.

    Defaults match the values previously in config.py so that existing
    deployments behave identically after migration.
    """
    existing_count = session.query(AppSetting).count()
    if existing_count > 0:
        return

    defaults = {
        # Grid detection (image analysis)
        "enable_image_grid_detection": True,
        "grid_min_cell_px": 32,
        "grid_max_cell_px": 320,
        "grid_detection_max_dim": 20000,
        "grid_presence_threshold": 0.20,
        "grid_size_threshold": 0.15,
        "grid_period_ratio_threshold": 0.98,
        "grid_hex_rot_conf": 0.20,
        # Color extraction
        "num_dominant_colors": 5,
        "color_distance_threshold": 0.35,
        "color_clustering_samples": 5000,
        "color_kmeans_n_init": 3,
        # Ingestion performance
        "ingestion_batch_size": 16,
        "max_concurrent_prepare": 8,
        # Import limits
        "max_import_file_size": 2000 * 1024 * 1024,
        "max_video_file_size": 2000 * 1024 * 1024,
        "max_import_files": 1000,
        "max_import_total_size": 2048 * 1024 * 1024,
        # Job runner
        "max_job_workers": 2,
        "scheduler_enabled": True,
    }

    for key, value in defaults.items():
        session.add(AppSetting(key=key, value_json=json.dumps(value)))

    session.commit()
    logger.info(f"Seeded {len(defaults)} default app settings")
