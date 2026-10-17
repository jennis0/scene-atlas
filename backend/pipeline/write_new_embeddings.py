"""Regenerate all CLIP embeddings and write them to LanceDB.

Reads every image from the database, encodes it with CLIP, and upserts the
embedding into LanceDB.  The existing collection is deleted and recreated so
stale entries are cleaned up.

Designed to run as a background job via the JobRunner (triggered from the API)
so it shares the server's embedded LanceDB instance.
"""

import logging

from backend.app.config import settings
from backend.app.models import Image, get_engine, get_session_local
from backend.app.services import get_image_store
from backend.app.services.clip_service import get_clip_service
from backend.app.services.lancedb_service import get_lancedb_service

logger = logging.getLogger(__name__)


def rebuild_all_embeddings(progress_fn=None, *, force: bool = False) -> dict:
    """Delete and regenerate all embeddings.

    Without *force*, skips the rebuild if the collection already holds the expected
    number of embeddings. Returns total/succeeded/failed counts.
    """
    svc = get_lancedb_service()
    clip_service = get_clip_service()
    image_store = get_image_store()

    # Count images in SQLite
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

    # Skip rebuild if collection already populated (unless forced)
    if not force:
        try:
            info = svc.get_collection_info()
            existing_count = info.get("points_count", 0)
            if existing_count == total and total > 0:
                logger.info(
                    "Collection already has %s embeddings matching %s images — skipping rebuild. "
                    "Use force=True to rebuild anyway.",
                    existing_count,
                    total,
                )
                return {"total": total, "succeeded": total, "failed": 0, "skipped": True}
        except Exception:
            logger.debug("Could not check collection info, proceeding with rebuild")

    # Wipe and recreate the collection so stale entries are removed
    logger.info("Recreating LanceDB collection...")
    svc.delete_collection()
    svc.ensure_collection()

    logger.info("Rebuilding embeddings for %s images...", total)

    succeeded = 0
    failed = 0
    svc_batch_size = 100  # Write batch for LanceDB upserts
    encode_batch_size = 16  # GPU forward-pass batch for ONNX vision encoder

    for i in range(0, total, svc_batch_size):
        batch = image_dicts[i : i + svc_batch_size]
        batch_num = i // svc_batch_size + 1
        total_batches = (total + svc_batch_size - 1) // svc_batch_size
        logger.info("Batch %s/%s (%s images)", batch_num, total_batches, len(batch))

        # Resolve paths and filter out missing files
        valid_recs = []
        paths = []
        for rec in batch:
            try:
                paths.append(image_store.get_path(rec["storage_key"]))
                valid_recs.append(rec)
            except Exception:
                logger.warning(
                    "Failed to locate image %s (%s)", rec["id"], rec["filename"], exc_info=True
                )
                failed += 1

        # Encode in GPU-sized sub-batches using batch_encode_images()
        items = []
        for j in range(0, len(valid_recs), encode_batch_size):
            sub_paths = paths[j : j + encode_batch_size]
            sub_recs = valid_recs[j : j + encode_batch_size]
            try:
                embeddings = clip_service.batch_encode_images(sub_paths)
                for rec, embedding in zip(sub_recs, embeddings, strict=True):
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
                logger.warning(
                    "Batch encode failed for %d images, falling back to one-at-a-time",
                    len(sub_paths),
                    exc_info=True,
                )
                for path, rec in zip(sub_paths, sub_recs, strict=True):
                    try:
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
                        logger.warning(
                            "Failed to encode image %s (%s)",
                            rec["id"],
                            rec["filename"],
                            exc_info=True,
                        )
                        failed += 1

        # Write batch to LanceDB
        if items:
            ok = svc.batch_add_embeddings(items)
            if ok:
                succeeded += len(items)
            else:
                failed += len(items)
                logger.error("Batch %s LanceDB write failed", batch_num)

        if progress_fn:
            progress_fn(min(i + svc_batch_size, total), total, f"Batch {batch_num}/{total_batches}")

    summary = {"total": total, "succeeded": succeeded, "failed": failed, "skipped": False}
    logger.info("Embedding rebuild complete: %s", summary)
    return summary
