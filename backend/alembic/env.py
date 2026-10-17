"""Alembic migration environment.

The database URL is read from the Alembic Config object so migrations always
target the correct database — whether that is the production DB (set in
alembic.ini) or a temporary test DB (set programmatically by init_db()).
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

# Ensure the project root is on the path so `backend` package imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import our SQLAlchemy models metadata
from backend.app.models.database import Base

# Alembic Config object — gives access to values in alembic.ini
config = context.config

# Set up logging from alembic.ini if a config file is present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    """Read the database URL from the Alembic Config.

    When called via init_db(), the caller sets ``sqlalchemy.url`` on the
    Config object so this always targets the correct database (including
    temporary test databases).  When called from the CLI, the value in
    alembic.ini is used.
    """
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url is not configured")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL, doesn't connect).

    Used with ``alembic upgrade --sql``.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE workarounds
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to database)."""
    url = get_url()
    # check_same_thread=False allows Alembic to use the connection from any thread
    connect_args = {"check_same_thread": False} if "sqlite" in url else {}
    engine = create_engine(url, connect_args=connect_args)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE workarounds
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
