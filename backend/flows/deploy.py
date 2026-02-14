"""Register Prefect deployments.

Run this script after the Prefect server is up to register flow deployments.

Usage:
    uv run python -m backend.flows.deploy
"""

import os

# Ensure Prefect client points to our server
os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

from backend.flows.ingestion import import_images


def main():
    """Register the import_images flow as a Prefect deployment."""
    print("Registering Prefect deployments...")

    import_images.deploy(
        name="import-ingestion",
        work_pool_name="battlemap-pool",
    )

    print("Deployment 'import-images/import-ingestion' registered successfully")
    print("Make sure a worker is running: uv run prefect worker start --pool battlemap-pool")


if __name__ == "__main__":
    main()
