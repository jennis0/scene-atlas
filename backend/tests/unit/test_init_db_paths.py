"""init_db() works wherever the user keeps their data.

SQLAlchemy 2.1 percent-encodes the database path when it renders a URL (the ':' and
'\\' of every Windows path, and any '%'), and Alembic's Config is a ConfigParser,
which reads '%' as interpolation syntax. Handing it the rendered URL stopped the
backend from starting on Windows; init_db now passes Alembic its connection instead.
"""

import pytest
from sqlalchemy import inspect

from backend.app.models import get_engine, init_db


# Names valid on every OS. On Windows, tmp_path itself adds 'C:\'.
@pytest.mark.parametrize("folder", ["100% maps", "Scene Atlas", "Cartes de donjon é"])
def test_init_db_in_awkward_folders(tmp_path, folder):
    db_path = tmp_path / folder / "battlemap.db"
    db_path.parent.mkdir()
    engine = get_engine(f"sqlite:///{db_path}")

    init_db(engine)  # fresh database: runs every migration
    init_db(engine)  # Alembic-managed: upgrade is a no-op

    assert db_path.exists()
    assert "images" in inspect(engine).get_table_names()
