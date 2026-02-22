"""Register Prefect deployments.

Run this script after the Prefect server is up to register flow deployments.

Usage:
    uv run python -m backend.flows.deploy

Prerequisites:
    - Prefect server running (docker compose up -d)
    - PREFECT_API_URL set (defaults to http://localhost:4200/api)
"""

import asyncio
import os
from pathlib import Path

# Ensure Prefect client points to our server
os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

from prefect.client.orchestration import get_client

from backend.app.config import settings
from backend.flows.ingestion import analyse_upload, process_import_group, process_import_job
from backend.flows.maintenance import backup_database, cleanup_staging
from backend.flows.backfill_content_hash import backfill_content_hash
from backend.flows.write_new_embeddings import write_new_embeddings

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

    # write_new_embeddings: one-off flow to backfill Qdrant with CLIP embeddings for existing images
    write_new_embeddings.from_source(
        source=PROJECT_ROOT, entrypoint="backend/flows/write_new_embeddings.py:write_new_embeddings"
    ).deploy(
        name="write-new-embeddings-deployment",
        work_pool_name=settings.prefect_work_pool,
    )
    print(f"  Registered: {settings.process_job_deployment}/backfill-embeddings-job")

    # backfill_content_hash: one-off flow to compute SHA-256 for existing images
    backfill_content_hash.from_source(
        source=PROJECT_ROOT, entrypoint="backend/flows/backfill_content_hash.py:backfill_content_hash"
    ).deploy(
        name="backfill-content-hash-deployment",
        work_pool_name=WORK_POOL,
    )
    print("  Registered: backfill-content-hash-deployment/backfill-content-hash")

    # backup_database: runs daily at 03:00 UTC
    backup_database.from_source(
        source=PROJECT_ROOT,
        entrypoint="backend/flows/maintenance.py:backup_database",
    ).deploy(
        name="backup-deployment",
        work_pool_name=WORK_POOL,
        schedules=[{"cron": "0 3 * * *", "timezone": "UTC"}],
    )
    print("  Registered: backup-deployment/backup-database (daily 03:00 UTC)")

    # cleanup_staging: runs every 6 hours
    cleanup_staging.from_source(
        source=PROJECT_ROOT,
        entrypoint="backend/flows/maintenance.py:cleanup_staging",
    ).deploy(
        name="cleanup-staging-deployment",
        work_pool_name=WORK_POOL,
        schedules=[{"cron": "0 */6 * * *", "timezone": "UTC"}],
    )
    print("  Registered: cleanup-staging-deployment/cleanup-staging (every 6h)")

    # Register concurrency limit for CLIP tasks — only one CLIP model
    # instance should load at a time across all concurrent flows
    async def _set_clip_limit():
        async with get_client() as client:
            await client.create_concurrency_limit(tag="clip", concurrency_limit=1)

    asyncio.run(_set_clip_limit())
    print("  Registered: clip tag concurrency limit = 1")

    print()
    print("Deployments registered successfully.")
    print(f"Start a worker: uv run prefect worker start --pool {WORK_POOL}")


if __name__ == "__main__":
    main()
