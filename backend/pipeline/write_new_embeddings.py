"""Regenerate all CLIP embeddings and write them to Qdrant.

Reads every image from the database, encodes it with CLIP, and upserts the
embedding into Qdrant.  The existing collection is deleted and recreated so
stale entries are cleaned up.

Designed to run as a background job via the JobRunner (triggered from the API)
so it shares the server's embedded Qdrant instance.
"""

import logging

from backend.app.config import settings
from backend.app.models import Image, get_engine, get_session_local
from backend.app.services import get_image_store
from backend.app.services.clip_service import get_clip_service
from backend.app.services.qdrant_service import get_qdrant_service

logger = logging.getLogger(__name__)


def rebuild_all_embeddings(progress_fn=None) -> dict:
    """Delete and regenerate all CLIP embeddings.

    Parameters
    ----------
    progress_fn:
        Optional callback ``(current, total, message)`` injected by JobRunner.

    Returns a summary dict with total/succeeded/failed counts.
    """
    qdrant = get_qdrant_service()
    clip_service = get_clip_service()
    image_store = get_image_store()

    # Wipe and recreate the collection so stale entries are removed
    logger.info("Recreating Qdrant collection...")
    qdrant.delete_collection()
    qdrant.ensure_collection()

    # Load all image records
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        images = db.query(Image).all()
        image_dicts = [
            {
                "id": img.id,
                "storage_key": img.storage_key,
                "filename": img.filename,
                "author": img.author,
                "group_name": img.group_name or "",
            }
            for img in images
        ]
    finally:
        db.close()

    total = len(image_dicts)
    logger.info(f"Rebuilding embeddings for {total} images...")

    succeeded = 0
    failed = 0
    batch_size = 100

    for i in range(0, total, batch_size):
        batch = image_dicts[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch)} images)")

        # Encode images
        items = []
        for rec in batch:
            try:
                path = image_store.get_path(rec["storage_key"])
                embedding = clip_service.encode_image(path)
                items.append(
                    {
                        "image_id": rec["id"],
                        "embedding": embedding,
                        "metadata": {
                            "filename": rec["filename"],
                            "author": rec["author"],
                            "base_name": rec["group_name"],
                        },
                    }
                )
            except Exception:
                logger.warning(f"Failed to encode image {rec['id']} ({rec['filename']})", exc_info=True)
                failed += 1

        # Write batch to Qdrant
        if items:
            ok = qdrant.batch_add_embeddings(items)
            if ok:
                succeeded += len(items)
            else:
                failed += len(items)
                logger.error(f"Batch {batch_num} Qdrant write failed")

        if progress_fn:
            progress_fn(min(i + batch_size, total), total, f"Batch {batch_num}/{total_batches}")

    summary = {"total": total, "succeeded": succeeded, "failed": failed}
    logger.info(f"Embedding rebuild complete: {summary}")
    return summary
