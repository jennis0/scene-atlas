"""Test server startup."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Try to import and check for errors
try:
    print("Testing imports...")
    from backend.app.main import app
    from backend.app.config import settings

    print("[OK] Imports successful")
    print(f"[OK] App: {settings.app_name}")
    print(f"[OK] Database URL: {settings.database_url}")
    print(f"[OK] Qdrant: {settings.qdrant_host}:{settings.qdrant_port}")

    # Try to initialize database
    print("\nTesting database initialization...")
    from backend.app.models import get_engine, init_db, seed_tag_categories, get_session_local

    engine = get_engine(settings.database_url)
    init_db(engine)
    print("[OK] Database initialized")

    SessionLocal = get_session_local(engine)
    session = SessionLocal()
    try:
        seed_tag_categories(session)
        print("[OK] Tag categories seeded")
    finally:
        session.close()

    print("\n=== All startup checks passed! ===")
    print(f"\nTo start the server, run:")
    print(f"  uv run python -m backend.app.main")

except Exception as e:
    print(f"\n[ERROR] Error during startup:")
    import traceback

    traceback.print_exc()
    sys.exit(1)
