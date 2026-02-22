"""Clean up database for fresh start."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.app.config import settings
from backend.app.models import Base, get_engine, get_session_local
from backend.app.services.qdrant_service import QdrantService

print("Cleaning up database...")

# Get engine and drop all tables
engine = get_engine(settings.database_url)

# Drop all tables
Base.metadata.drop_all(bind=engine)
print("[OK] All tables dropped")

# Recreate all tables
Base.metadata.create_all(bind=engine)
print("[OK] All tables recreated")

# Seed tag categories
from backend.app.models import seed_tag_categories  # noqa: E402

SessionLocal = get_session_local(engine)
session = SessionLocal()
try:
    seed_tag_categories(session)
    print("[OK] Tag categories seeded")
finally:
    session.close()

# Clean up Qdrant collection
qdrant = QdrantService()
qdrant.delete_collection()
print("[OK] Qdrant collection dropped")

qdrant.ensure_collection()
print("[OK] Qdrant collection recreated")

print("\n=== Database cleaned and reset! ===")
