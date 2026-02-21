"""Register Prefect deployments.

Run this script after the Prefect server is up to register flow deployments.

Usage:
    uv run python -m backend.flows.deploy

Prerequisites:
    - Prefect server running (docker compose up -d)
    - PREFECT_API_URL set (defaults to http://localhost:4200/api)
"""

import os
from pathlib import Path

# Ensure Prefect client points to our server
os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

from backend.app.config import settings
from backend.flows.ingestion import analyse_upload, process_import_group, process_import_job

# Project root for from_source entrypoints
PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
WORK_POOL = settings.prefect_work_pool


def main():
    """Register all flow deployments."""
    print(f"Registering Prefect deployments to pool '{WORK_POOL}'...")
    print(f"Project root: {PROJECT_ROOT}")

    # analyse_upload: called synchronously by upload endpoint
    analyse_upload.from_source(
        source=PROJECT_ROOT,
        entrypoint="backend/flows/ingestion.py:analyse_upload",
    ).deploy(
        name=settings.analyse_deployment,
        work_pool_name=WORK_POOL,
    )
    print(f"  Registered: {settings.analyse_deployment}/analyse-upload")

    # process_import_group: called async by confirm endpoint
    process_import_group.from_source(
        source=PROJECT_ROOT,
        entrypoint="backend/flows/ingestion.py:process_import_group",
    ).deploy(
        name=settings.process_deployment,
        work_pool_name=WORK_POOL,
    )
    print(f"  Registered: {settings.process_deployment}/process-import-group")

    # process_import_job: handles all groups in one flow run (CLIP loaded once)
    process_import_job.from_source(
        source=PROJECT_ROOT,
        entrypoint="backend/flows/ingestion.py:process_import_job",
    ).deploy(
        name=settings.process_job_deployment,
        work_pool_name=WORK_POOL,
    )
    print(f"  Registered: {settings.process_job_deployment}/process-import-job")

    print()
    print("Deployments registered successfully.")
    print(f"Start a worker: uv run prefect worker start --pool {WORK_POOL}")


if __name__ == "__main__":
    main()
