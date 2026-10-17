"""Keep the LanceDB vector index consistent with SQLite by image id (ADR-018, design §5.3).

SQLite is the source of truth. Images are committed before their vectors are
written, so a crash or a failed vector write leaves images without vectors;
failed deletes leave vectors without images. This compares the two id sets
(not counts, which can hide offsetting errors), re-embeds the missing images
from their stored medium thumbnails (what imports embed), and deletes the
orphaned vectors.

It is also how every image is re-embedded after a model switch: the new model's
table starts empty, so every image is missing. Vectors are written batch by
batch, so a run that stops part-way leaves its work in place and the next run
(at startup) carries on from there.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from backend.app.models import Image, ImageGroup
from backend.app.services import get_lancedb_service, get_thumbnail_store
from backend.app.services.shutdown import raise_if_shutting_down

from .db import pipeline_db
from .tasks import embedding_generation

logger = logging.getLogger(__name__)

_DELETE_CHUNK = 500
# Writes that fail this many batches in a row stop the run: something is wrong with the
# index (disk, memory), and carrying on would only report progress while saving nothing.
MAX_FAILED_WRITES = 3

ProgressFn = Callable[[int, int, str], None]


class VectorWriteError(RuntimeError):
    """The search index kept refusing writes."""


@dataclass
class _Tally:
    repaired: int = 0
    unrepairable: int = 0
    failed_writes: int = 0  # consecutive


def _to_embed(chunk: list[int], tally: _Tally) -> list[tuple[int, str, str, str | None, str]]:
    """(id, thumbnail path, filename, author, group name) for the chunk's images that
    have a thumbnail; the rest are counted as unrepairable."""
    thumbnail_store = get_thumbnail_store()
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
                tally.unrepairable += 1
                continue
            base = group.base_name if group else ""
            pending.append((image_id, str(source), filename, author, base))
    return pending


def _embed_and_write(pending: list[tuple[int, str, str, str | None, str]], tally: _Tally) -> None:
    try:
        embeddings = embedding_generation.batch_generate_clip_embeddings(
            [source for _, source, _, _, _ in pending]
        )
    except Exception:
        logger.warning("Re-embedding %d image(s) failed; will retry next run", len(pending))
        return
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
    if get_lancedb_service().batch_add_embeddings(items):
        tally.repaired += len(items)
        tally.failed_writes = 0
        return
    tally.failed_writes += 1
    if tally.failed_writes >= MAX_FAILED_WRITES:
        raise VectorWriteError(
            "Couldn't save image embeddings to the search index; the log has the details"
        )


def reconcile_vectors(
    batch_size: int = 32, progress_fn: ProgressFn | None = None
) -> dict[str, int]:
    """Re-embed images missing a vector and delete vectors with no image.

    ``progress_fn(done, total, message)`` is called as images are re-embedded (the job
    runner passes one). Raises ``VectorWriteError`` if the index refuses
    ``MAX_FAILED_WRITES`` batches in a row.

    Returns counts: ``missing``, ``repaired``, ``unrepairable`` and ``orphaned``.
    """
    svc = get_lancedb_service()
    with pipeline_db() as db:
        image_ids = {image_id for (image_id,) in db.query(Image.id).all()}
    vector_ids = svc.get_all_ids()

    missing = sorted(image_ids - vector_ids)
    orphaned = sorted(vector_ids - image_ids)

    for start in range(0, len(orphaned), _DELETE_CHUNK):
        raise_if_shutting_down()
        svc.delete_embeddings(orphaned[start : start + _DELETE_CHUNK])

    tally = _Tally()
    for start in range(0, len(missing), batch_size):
        raise_if_shutting_down()  # what's left is still missing next run
        if progress_fn:
            progress_fn(start, len(missing), f"{start:,} of {len(missing):,} images")
        pending = _to_embed(missing[start : start + batch_size], tally)
        if pending:
            _embed_and_write(pending, tally)
    if progress_fn and missing:
        progress_fn(len(missing), len(missing), f"{len(missing):,} images")

    if missing or orphaned:
        logger.warning(
            "Vector reconciliation: %d missing (%d repaired, %d unrepairable), %d orphaned",
            len(missing),
            tally.repaired,
            tally.unrepairable,
            len(orphaned),
        )
    return {
        "missing": len(missing),
        "repaired": tally.repaired,
        "unrepairable": tally.unrepairable,
        "orphaned": len(orphaned),
    }
