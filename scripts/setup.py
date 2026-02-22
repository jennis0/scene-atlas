"""One-time setup: create Prefect work pool and register all flow deployments.

Run this ONCE after installing for the first time, and again whenever you add
new flows or change deployment configuration.

Prerequisites — complete these before running:
  1. uv sync --extra dev            # install Python + dev dependencies
  2. cd frontend && npm ci          # install frontend dependencies
  3. docker compose up -d           # start infrastructure
  4. wait ~60s for Prefect to start (check http://localhost:4200)

Usage:
  uv run python scripts/setup.py
"""

import asyncio
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

PREFECT_API = "http://localhost:4200/api"
WORK_POOL = "battlemap-pool"


def _wait_for_prefect(timeout: int = 120) -> None:
    """Poll until the Prefect server health endpoint responds."""
    print(f"  Polling {PREFECT_API}/health", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{PREFECT_API}/health", timeout=3)
            print(" ✓")
            return
        except Exception:
            print(".", end="", flush=True)
            time.sleep(3)
    print()
    print("\nERROR: Prefect server did not respond within the timeout.")
    print("  Make sure Docker infrastructure is running:")
    print("    docker compose up -d")
    print("  Then wait ~60s and retry.")
    sys.exit(1)


async def _ensure_work_pool() -> None:
    """Create the 'process' work pool if it doesn't already exist."""
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.actions import WorkPoolCreate
    from prefect.exceptions import ObjectNotFound

    async with get_client() as client:
        try:
            await client.read_work_pool(WORK_POOL)
            print(f"  Work pool '{WORK_POOL}' already exists — skipping.")
        except ObjectNotFound:
            await client.create_work_pool(WorkPoolCreate(name=WORK_POOL, type="process"))
            print(f"  Created work pool '{WORK_POOL}'.")


def _register_deployments() -> None:
    from backend.flows.deploy import main as deploy_main
    deploy_main()


def main() -> None:
    print("=" * 50)
    print("  Battlemap Explorer — First-Time Setup")
    print("=" * 50)
    print()

    print("[1/3] Checking Prefect server...")
    _wait_for_prefect()

    print("\n[2/3] Creating work pool...")
    asyncio.run(_ensure_work_pool())

    print("\n[3/3] Registering Prefect deployments...")
    _register_deployments()

    print()
    print("=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print()
    print("To start all services:")
    print("  uv run python scripts/start.py")
    print()
    print("Then open a second terminal for the frontend:")
    print("  cd frontend && npm run dev  →  http://localhost:5173")


if __name__ == "__main__":
    main()
