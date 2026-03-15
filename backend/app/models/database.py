"""SQLAlchemy database models for Scene Atlas."""

import json
import logging
import os
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
    import_job_id = Column(
        String, ForeignKey("import_jobs.id"), nullable=True, index=True
    )  # Import job that created this row; None for pre-existing/manually added images
    # NOTE: If you ever add relationship("ImportJob", ...) here, do NOT use
    # cascade="all, delete-orphan" — images may share storage_key with images
    # from other imports, so deleting the job must not cascade-delete images.

    # Storage keys (resolved via ImageStore at runtime)
    thumbnail_key = Column(String)  # Key into thumbnail store (e.g., "a1b2c3d4_400x400.jpg")

    # Metadata
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
        return self.group.image_count if self.group else None

    def __repr__(self):
        return f"<Image(id={self.id}, name='{self.name}', filename='{self.filename}')>"


class ImageGroup(Base):
    """Groups related scenes together."""

    __tablename__ = "variant_groups"

    id = Column(Integer, primary_key=True, index=True)
    base_name = Column(String, nullable=False, index=True)
    author = Column(String, index=True)
    primary_image_id = Column(Integer, ForeignKey("images.id"), nullable=True)
    image_count = Column(Integer, nullable=False, default=0)  # Maintained by DB triggers
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
    # status values: uploading, staging, active, completed, failed, cancelled, expired, broken
    source_label = Column(String, nullable=True)  # Display label for import tray
    total_files = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    # JSON: full analysis output — used for reconnection (rebuilding preview UI)
    analysis_result = Column(Text, nullable=True)
    job_warnings = Column(
        Text, nullable=True
    )  # JSON list of warning dicts (upload skips, pipeline warnings)
    total_file_size = Column(Integer, default=0)  # Accumulated bytes across all upload batches

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
    file_errors = Column(Text, nullable=True)  # JSON list of per-file error dicts
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

# Module-level engine cache keyed by database_url.  Previously every call to
# get_engine() created a brand-new SQLAlchemy Engine (and connection pool).
# During a large import the pipeline calls get_engine() 10+ times per group,
# producing hundreds of orphaned engines whose connection pools were never
# disposed — a steady memory leak.
_engine_cache: dict = {}


def get_engine(database_url: str = "sqlite:///./data/battlemap.db"):
    """Return a cached database engine, creating one if needed.

    For SQLite databases, enables WAL journal mode and a 10-second busy timeout
    so concurrent writers from multiple import threads don't get immediate
    'database is locked' errors.  WAL mode allows concurrent reads during writes
    and serialises writes safely.  synchronous=NORMAL is the SQLite recommendation
    for WAL mode: safe against Python/OS crashes, ~3× faster than FULL.
    """
    if database_url in _engine_cache:
        return _engine_cache[database_url]

    if "sqlite" in database_url:
        from sqlalchemy.pool import NullPool

        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
    else:
        engine = create_engine(database_url)
    if "sqlite" in database_url:
        from sqlalchemy import event as _sa_event

        @_sa_event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")  # 10 seconds
            cursor.execute("PRAGMA synchronous=NORMAL")  # recommended for WAL
            cursor.close()

    _engine_cache[database_url] = engine
    return engine


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
                sub_variant, thumbnail_key, created_at, updated_at
            )
            SELECT
                id, filename, storage_key, name, author, variant_group_id,
                width, height, file_size, gridded, grid_width, grid_height,
                sub_variant, thumbnail_key, created_at, updated_at
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
    # Prevent Alembic from calling logging.config.fileConfig(), which would
    # replace the root logger's handlers and remove our rotating file handler.
    # Logging is managed entirely by setup_logging() in logging_config.py.
    alembic_cfg.config_file_name = None

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
        logger.info("Running Alembic upgrade (current: %s)", current_rev)
        command.upgrade(alembic_cfg, "head")


def seed_tag_categories(session):
    """Seed initial tag categories with vocabulary for auto-tagging.

    Only runs when the tag_categories table is completely empty (first boot).
    Once categories exist, this is a no-op so user edits are preserved.

    Reads the canonical vocabulary from backend/app/data/tag_vocabulary.json.
    The ImageParser loads these to build its tag vocabulary.
    """
    existing_count = session.query(TagCategory).count()
    if existing_count > 0:
        return

    from backend.app.data.vocabulary import build_common_values_json, load_vocabulary

    vocab = load_vocabulary()

    for cat_data in vocab["categories"]:
        session.add(
            TagCategory(
                name=cat_data["name"],
                description=cat_data["description"],
                color=cat_data["color"],
                icon=cat_data.get("icon"),
                display_order=cat_data["display_order"],
                common_values=build_common_values_json(cat_data["tags"]),
            )
        )

    session.commit()


def seed_default_settings(session):
    """Seed default app settings into the DB on first boot.

    Only runs when the app_settings table is completely empty.
    Once any setting row exists, this is a no-op so user-edited values are preserved.

    Concurrency settings use resource_detector to compute host-appropriate defaults
    based on CPU count and available RAM. Import limits and algorithm params use
    sensible fixed defaults.
    """
    from backend.app.resource_detector import compute_resource_defaults

    existing_count = session.query(AppSetting).count()
    if existing_count > 0:
        return

    resource_defaults = compute_resource_defaults()

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
        # Ingestion performance — resource-aware defaults
        "ingestion_batch_size": 16,
        "max_concurrent_prepare": resource_defaults["max_concurrent_prepare"],
        "max_concurrent_heavy_requests": resource_defaults["max_concurrent_heavy_requests"],
        # Import limits — sensible hardcoded defaults (change via admin API)
        "max_import_file_size": 2 * 1024 * 1024 * 1024,  # 2 GB
        "max_video_file_size": 2 * 1024 * 1024 * 1024,  # 2 GB
        "max_import_files": 1000,
        "max_import_total_size": 2 * 1024 * 1024 * 1024,  # 2 GB
        # Job runner — resource-aware default
        "max_job_workers": resource_defaults["max_job_workers"],
        "scheduler_enabled": True,
        # Import processing — initial value read from env so setup wizard choice is honoured
        "convert_to_webp": bool(int(os.environ.get("CONVERT_TO_WEBP", "1"))),
        "webp_lossless": True,
        "webp_quality": 95,
    }

    for key, value in defaults.items():
        session.add(AppSetting(key=key, value_json=json.dumps(value)))

    session.commit()
    logger.info("Seeded %s default app settings", len(defaults))
