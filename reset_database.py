#!/usr/bin/env python3
"""Quick script to reset the database and Qdrant collection."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    print("=" * 60)
    print("RESETTING DATABASE")
    print("=" * 60)
    print()

    # Run the cleanup script
    cleanup_script = Path(__file__).parent / "backend" / "tests" / "cleanup_database.py"
    result = subprocess.run([sys.executable, str(cleanup_script)])

    if result.returncode == 0:
        print("\n✓ Database reset complete!")
        print("\nYou can now run the ingestion flow to populate with fresh data:")
        print("  python run_ingestion.py")
        print("\nOr with custom directories:")
        print("  python run_ingestion.py path/to/images path/to/more/images")
    else:
        print("\n✗ Database reset failed!")
        sys.exit(1)
