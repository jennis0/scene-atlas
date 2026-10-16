"""SQLAlchemy database models for Scene Atlas."""

import json
import logging
import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Image(Base):
    """Main image table."""

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False, index=True)  # For display
    storage_key: Mapped[str] = mapped_column(String, nullable=False, index=True)  # ImageStore key
    name: Mapped[str | None] = mapped_column(String, index=True)  # Inferred base name
    author: Mapped[str | None] = mapped_column(String, index=True)
    group_id: Mapped[int | None] = mapped_column(
        "variant_group_id", Integer, ForeignKey("variant_groups.id"), nullable=True, index=True
    )

    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    file_size: Mapped[int | None] = mapped_column(Integer)  # In bytes
    gridded: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, index=True
    )  # None = unknown
    grid_width: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Tile count
    grid_height: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Tile count
    grid_type: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )  # "square" | "hex"
    grid_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 0.0-1.0, None = filename-detected
    subgroup: Mapped[str | None] = mapped_column(
        "sub_variant", String, nullable=True
    )  # e.g. "MA / No Grid"
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # SHA-256 of original bytes
    stored_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # SHA-256 of the stored file
    pixel_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # Hash of canonical decoded pixels
    phash: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 64-bit perceptual hash (signed); advisory only
    search_text: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Pre-tokenized for FTS5 (CamelCase-split)
    media_type: Mapped[str | None] = mapped_column(
        String, nullable=True, default="image", index=True
    )
    image_type: Mapped[str | None] = mapped_column(
        String, nullable=True, default="battlemap", index=True
    )
    # None for images that predate import jobs.
    # Never add a cascading relationship to ImportJob here: dismissing or pruning a job
    # must not delete its images (only an explicit Undo does).
    import_job_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("import_jobs.id"), nullable=True, index=True
    )
    thumbnail_key: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="image", cascade="all, delete-orphan"
    )
    colors: Mapped[list["Color"]] = relationship(
        "Color", back_populates="image", cascade="all, delete-orphan"
    )
    group: Mapped["ImageGroup | None"] = relationship(
        "ImageGroup", back_populates="images", foreign_keys="[Image.group_id]"
    )

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    base_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    author: Mapped[str | None] = mapped_column(String, index=True)
    primary_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id"), nullable=True
    )
    image_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Maintained by DB triggers
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["Image"]] = relationship(
        "Image", back_populates="group", foreign_keys="[Image.group_id]"
    )

    def __repr__(self):
        return f"<ImageGroup(id={self.id}, base_name='{self.base_name}')>"


class Tag(Base):
    """Tag system for multidimensional variant categorization."""

    __tablename__ = "tags"
    __table_args__ = (Index("ix_tags_category_value", "category", "value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)  # e.g. 'season'
    value: Mapped[str] = mapped_column(String, nullable=False, index=True)  # e.g. 'winter'
    confidence: Mapped[float | None] = mapped_column(Float, default=1.0)  # <1 for auto tags
    source: Mapped[str | None] = mapped_column(String, default="manual")  # 'auto' | 'manual'
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    image: Mapped["Image"] = relationship("Image", back_populates="tags")

    def __repr__(self):
        return (
            f"<Tag(category='{self.category}', value='{self.value}', confidence={self.confidence})>"
        )


class TagCategory(Base):
    """Defines available tag categories and their common values."""

    __tablename__ = "tag_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    common_values: Mapped[str | None] = mapped_column(Text)  # JSON array
    color: Mapped[str | None] = mapped_column(String, nullable=True)  # Tailwind preset name
    icon: Mapped[str | None] = mapped_column(String, nullable=True)  # Lucide icon name
    display_order: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TagCategory(name='{self.name}')>"


class Color(Base):
    """Dominant colors extracted from images."""

    __tablename__ = "colors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id"), nullable=False, index=True
    )
    color_hex: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # '#1a2b3c'
    percentage: Mapped[float | None] = mapped_column(Float)  # 0.0-100.0
    color_order: Mapped[int | None] = mapped_column(Integer)  # 1 = most dominant

    image: Mapped["Image"] = relationship("Image", back_populates="colors")

    def __repr__(self):
        return f"<Color(hex='{self.color_hex}', percentage={self.percentage})>"


class ImportJob(Base):
    """One import the user started (ADR-018). Aggregates its groups and items.

    Status (``active`` | ``paused`` | ``completed`` | ``cancelled``) is derived
    from item counts by ``ingest_queue.recompute_job_status``; a job never fails
    as a whole.
    """

    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID hex
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    source_label: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "Pack.zip"
    default_image_type: Mapped[str] = mapped_column(String, nullable=False, default="battlemap")
    planned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Sealed
    last_upload_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Hidden from the activity dock
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    import_groups: Mapped[list["ImportGroup"]] = relationship(
        "ImportGroup", back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    items: Mapped[list["ImportItem"]] = relationship(
        "ImportItem", back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self):
        return f"<ImportJob(id='{self.id}', status='{self.status}')>"


class AppSetting(Base):
    """Key-value store for DB-backed application settings (feature flags, tuning params)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<AppSetting(key='{self.key}', value_json='{self.value_json}')>"


class ImportGroup(Base):
    """A group planned from the uploaded paths at seal time (ADR-018).

    Resolves to a gallery ``ImageGroup``: an existing one (``merged_into_existing``)
    or one created when the first image of the group commits.
    """

    __tablename__ = "import_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String, ForeignKey("import_jobs.id"), nullable=False, index=True
    )
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    group_name: Mapped[str] = mapped_column(String, nullable=False)
    image_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("variant_groups.id"), nullable=True
    )
    merged_into_existing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["ImportJob"] = relationship("ImportJob", back_populates="import_groups")

    def __repr__(self):
        return f"<ImportGroup(id={self.id}, group='{self.group_name}')>"


class ImportItem(Base):
    """One file in an import job. All durable ingest state lives here (ADR-018).

    State machine: see ``backend/app/services/ingest_state.py``.
    """

    __tablename__ = "import_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("import_jobs.id"), nullable=False)
    import_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_groups.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(
        String, nullable=False, default="image"
    )  # image | video | archive
    relative_path: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Display + resume matching only
    filename: Mapped[str] = mapped_column(String, nullable=False)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_modified: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Client-reported, ms since epoch
    image_type: Mapped[str] = mapped_column(String, nullable=False, default="battlemap")
    parsed: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON, set at plan time
    state: Mapped[str] = mapped_column(String, nullable=False, default="awaiting_bytes")
    staging_key: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Server-generated staged filename
    source_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # SHA-256 of the original bytes
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # file | transient | system
    error_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # User-facing
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # Raw exception text
    image_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("images.id"), nullable=True)
    duplicate_of_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id"), nullable=True
    )
    duplicate_tier: Mapped[str | None] = mapped_column(String, nullable=True)  # bytes | pixels
    allow_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    similar_to_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id"), nullable=True
    )
    similarity_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    job: Mapped["ImportJob"] = relationship("ImportJob", back_populates="items")

    __table_args__ = (
        UniqueConstraint("job_id", "relative_path", name="uq_import_items_job_path"),
        Index("ix_import_items_state_job", "state", "job_id"),
        Index("ix_import_items_job_state", "job_id", "state"),
        Index("ix_import_items_job_group", "job_id", "import_group_id"),
    )

    def __repr__(self):
        return f"<ImportItem(id={self.id}, path='{self.relative_path}', state='{self.state}')>"


# One engine (and connection pool) per database URL. Creating an engine per call
# leaks pools: the pipeline calls get_engine() many times per import group.
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
        bundle_dir = _Path(_sys._MEIPASS)  # pyright: ignore[reportAttributeAccessIssue]
        alembic_ini = bundle_dir / "alembic.ini"
        alembic_cfg = AlembicConfig(str(alembic_ini))
        alembic_cfg.set_main_option(
            "script_location",
            str(bundle_dir / "backend" / "alembic"),
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
        "grid_detection_max_dim": 8000,  # Phase 0: ~0.5% accuracy cost, 3-4x less CPU on huge maps
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
        "convert_to_webp": bool(int(os.environ.get("CONVERT_TO_WEBP", "0"))),
        "webp_lossless": True,
        "webp_quality": 95,
    }

    for key, value in defaults.items():
        session.add(AppSetting(key=key, value_json=json.dumps(value)))

    session.commit()
    logger.info("Seeded %s default app settings", len(defaults))
