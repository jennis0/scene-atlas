"""Alembic migration environment.

init_db() passes the app's own connection in ``config.attributes["connection"]``
and migrations run on it. Otherwise (the CLI, the migration tests) the database
URL comes from the Config: alembic.ini, or one set with set_main_option().
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, create_engine

# Ensure the project root is on the path so `backend` package imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import our SQLAlchemy models metadata
from backend.app.models.database import Base

# Alembic Config object — gives access to values in alembic.ini
config = context.config

# Set up logging from alembic.ini if a config file is present (the CLI). Never disable
# loggers that already exist: when Alembic runs inside the app or the test suite, that
# would silence every module's logger for the rest of the process.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    """Read the database URL from the Alembic Config (alembic.ini, or set by the caller)."""
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


def _run_on(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # required for SQLite ALTER TABLE workarounds
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to database)."""
    shared = config.attributes.get("connection")
    if shared is not None:
        _run_on(shared)
        return

    url = get_url()
    # check_same_thread=False allows Alembic to use the connection from any thread
    connect_args = {"check_same_thread": False} if "sqlite" in url else {}
    engine = create_engine(url, connect_args=connect_args)
    with engine.connect() as connection:
        _run_on(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
