"""Keep the LanceDB vector index consistent with SQLite by image id (ADR-018, design §5.3).

SQLite is the source of truth. Images are committed before their vectors are
written, so a crash or a failed vector write leaves images without vectors;
failed deletes leave vectors without images. This compares the two id sets
(not counts, which can hide offsetting errors), re-embeds the missing images
from their stored thumbnails, and deletes the orphaned vectors.
"""

from __future__ import annotations

import logging

from backend.app.models import Image, ImageGroup
from backend.app.services import get_lancedb_service, get_thumbnail_store

from .db import pipeline_db
from .tasks import embedding_generation

logger = logging.getLogger(__name__)

_DELETE_CHUNK = 500


def reconcile_vectors(batch_size: int = 32) -> dict[str, int]:
    """Re-embed images missing a vector and delete vectors with no image.

    Returns counts: ``missing``, ``repaired``, ``unrepairable`` and ``orphaned``.
    """
    svc = get_lancedb_service()
    with pipeline_db() as db:
        image_ids = {image_id for (image_id,) in db.query(Image.id).all()}
    vector_ids = svc.get_all_ids()

    missing = sorted(image_ids - vector_ids)
    orphaned = sorted(vector_ids - image_ids)

    for start in range(0, len(orphaned), _DELETE_CHUNK):
        svc.delete_embeddings(orphaned[start : start + _DELETE_CHUNK])

    repaired = unrepairable = 0
    thumbnail_store = get_thumbnail_store()
    for start in range(0, len(missing), batch_size):
        chunk = missing[start : start + batch_size]
        with pipeline_db() as db:
            rows = (
                db.query(Image.id, Image.filename, Image.author, Image.thumbnail_key, ImageGroup)
                .outerjoin(ImageGroup, ImageGroup.id == Image.group_id)
                .filter(Image.id.in_(chunk))
                .all()
            )
            pending = []
            for image_id, filename, author, thumbnail_key, group in rows:
                source = thumbnail_store.get_path(thumbnail_key) if thumbnail_key else None
                if source is None or not source.exists():
                    unrepairable += 1
                    continue
                pending.append(
                    (image_id, str(source), filename, author, group.base_name if group else "")
                )
        if not pending:
            continue
        try:
            embeddings = embedding_generation.batch_generate_clip_embeddings(
                [source for _, source, _, _, _ in pending]
            )
        except Exception:
            logger.warning("Re-embedding %d image(s) failed; will retry next run", len(pending))
            continue
        items = [
            {
                "image_id": image_id,
                "embedding": embedding,
                "metadata": {"filename": filename, "author": author or "", "base_name": base},
            }
            for (image_id, _, filename, author, base), embedding in zip(
                pending, embeddings, strict=True
            )
        ]
        if svc.batch_add_embeddings(items):
            repaired += len(items)

    if missing or orphaned:
        logger.warning(
            "Vector reconciliation: %d missing (%d repaired, %d unrepairable), %d orphaned",
            len(missing),
            repaired,
            unrepairable,
            len(orphaned),
        )
    return {
        "missing": len(missing),
        "repaired": repaired,
        "unrepairable": unrepairable,
        "orphaned": len(orphaned),
    }
