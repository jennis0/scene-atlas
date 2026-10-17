"""Re-embed every image: after a model switch, or when asked to rebuild.

Clears the active model's vector table and lets ``reconcile_vectors`` fill it again,
so a rebuild embeds exactly what imports embed (each image's medium thumbnail),
reports progress per image, and resumes after a restart: the startup
reconciliation re-embeds whatever is still missing.

Designed to run as a background job via the JobRunner so it shares the server's
embedded LanceDB instance.
"""

import logging

from backend.app.models import Image
from backend.app.services.lancedb_service import get_lancedb_service
from backend.pipeline.db import pipeline_db
from backend.pipeline.vector_reconcile import ProgressFn, reconcile_vectors

logger = logging.getLogger(__name__)


def rebuild_all_embeddings(progress_fn: ProgressFn | None = None, *, force: bool = False) -> dict:
    """Delete and regenerate all embeddings.

    Without *force*, skips the rebuild if the table already holds a vector for every
    image. Returns total/succeeded/failed counts.
    """
    svc = get_lancedb_service()
    with pipeline_db() as db:
        total = db.query(Image.id).count()

    if not force and total > 0 and len(svc.get_all_ids()) == total:
        logger.info("Every image already has an embedding; skipping rebuild")
        return {"total": total, "succeeded": total, "failed": 0, "skipped": True}

    logger.info("Re-embedding %s images", total)
    svc.delete_collection()
    svc.ensure_collection()
    result = reconcile_vectors(progress_fn=progress_fn)
    summary = {
        "total": total,
        "succeeded": result["repaired"],
        "failed": result["missing"] - result["repaired"],
        "skipped": False,
    }
    logger.info("Embedding rebuild complete: %s", summary)
    return summary
