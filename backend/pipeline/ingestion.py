"""Image ingestion pipeline orchestration.

Coordinates batched image processing by delegating to specialized modules:
- prepare.py: image preparation (parsing, thumbnails, colors, grid detection)
- persistence.py: database and Qdrant saves

Public API:
    process_import_group — Process one import group (batched pipeline)
    process_import_job   — Process multi-group import job
    process_single_image — End-to-end single image processing
    bulk_image_ingestion — CLI batch ingestion from directories
    analyse_upload       — Parse and preview uploaded files for web UI
"""

import gc
import logging
import time
from pathlib import Path

from backend.app.config import settings
from backend.app.models import (
    Image,
    ImageGroup,
    ImportJob,
)
from backend.app.process_utils import get_rss_mb
from backend.app.services import (
    get_image_store,
    get_qdrant_service,
    get_thumbnail_store,
)
from backend.app.services.fts_service import fts_rebuild
from backend.app.services.prepare_pool import get_prepare_pool
from backend.app.services.staging import (
    load_file_map as _load_file_map,
)

from .db import pipeline_db
from .error_classifier import classify_ingest_error
from .persistence import (
    batch_save_to_database,
    batch_save_to_qdrant,
    save_to_database,
    save_to_qdrant,
    update_import_group_job_progress,
)
from .pipeline_config import PipelineConfig, load_pipeline_config
from .prepare import (
    _build_parser,
    _collect_futures,
    _compute_file_hash,
    prepare_single_image,
    scan_directory,
)
from .tasks.embedding_generation import (
    batch_generate_clip_embeddings,
    generate_clip_embedding,
)


def _process_batch(
    prepared_results: list[dict],
) -> tuple[list[dict], int, list[dict]]:
    """Process a batch of prepared images: CLIP embed, DB save, Qdrant save.

    Handles two kinds of successful results:
    - New images: need CLIP embedding generation
    - Reuse images: retrieve existing embedding from Qdrant (or fall back to
      generating from the stored file if retrieval fails)

    Args:
        prepared_results: List of results from prepare_single_image

    Returns:
        Tuple of (all_results including failures, count of batch failures,
        list of warning dicts for non-fatal issues like Qdrant save failures)
    """
    logger = logging.getLogger(__name__)
    # Separate successes from failures
    successful = [r for r in prepared_results if r["status"] == "success"]
    batch_failed = len(prepared_results) - len(successful)

    if not successful:
        return prepared_results, batch_failed, []

    # Split into new images vs reuse images
    new_images = [r for r in successful if "reuse_embedding_from" not in r]
    reuse_images = [r for r in successful if "reuse_embedding_from" in r]

    # --- New images: batch CLIP embedding ---
    # Use clip_source_path (thumbnail for images, first-frame JPEG for videos).
    # clip_image_path is now only used for cleanup of temp video frames below.
    if new_images:
        image_paths = [r.get("clip_source_path") or r["original_image_path"] for r in new_images]
        try:
            embeddings = batch_generate_clip_embeddings(image_paths)
            for prep, embedding in zip(new_images, embeddings, strict=True):
                prep["embedding"] = embedding
        except Exception as clip_exc:
            logger.exception("Batch CLIP embedding failed for %d images", len(new_images))
            error_info = classify_ingest_error(clip_exc, stage="embedding")
            for prep in new_images:
                prep["status"] = "failed"
                prep["error"] = error_info["reason"]
                prep["error_info"] = error_info
                batch_failed += 1
        finally:
            # Clean up temp video frame files whether or not CLIP succeeded
            for prep in new_images:
                if prep.get("clip_image_path"):
                    Path(prep["clip_image_path"]).unlink(missing_ok=True)

    # --- Reuse images: retrieve existing embeddings from Qdrant in one batch call ---
    if reuse_images:
        source_ids = [prep["reuse_embedding_from"] for prep in reuse_images]
        embeddings_by_id = get_qdrant_service().get_embeddings(source_ids)
        for prep in reuse_images:
            source_id = prep["reuse_embedding_from"]
            embedding = embeddings_by_id.get(source_id)
            if embedding:
                prep["embedding"] = embedding
            else:
                # Fallback: generate from the stored file
                logger.warning(
                    "Could not retrieve embedding for source image %s, generating from stored file",
                    source_id,
                )
                stored_path = get_image_store().get_path(prep["image_data"]["storage_key"])
                if stored_path.exists():
                    prep["embedding"] = generate_clip_embedding(str(stored_path))
                else:
                    logger.error("Stored file not found for reuse: %s", stored_path)
                    error_info = classify_ingest_error(
                        FileNotFoundError(f"Stored file not found: {stored_path}"),
                        stage="embedding",
                    )
                    prep["status"] = "failed"
                    prep["error"] = error_info["reason"]
                    prep["error_info"] = error_info
                    batch_failed += 1

    # Re-filter to only truly successful results
    all_successful = [r for r in successful if r["status"] == "success"]

    # Batch DB save — isolated so a failure doesn't kill subsequent batches
    image_ids: list[int] = []
    if all_successful:
        image_data_list = [r["image_data"] for r in all_successful]
        try:
            image_ids = batch_save_to_database(image_data_list)
        except Exception as db_exc:
            logger.exception("Batch DB save failed for %d images", len(all_successful))
            error_info = classify_ingest_error(db_exc, stage="db_save")
            # Clean up files that were already copied to ImageStore — they have no
            # DB row to anchor them and will become permanently orphaned otherwise.
            # Skip reuse images: their storage_key belongs to an existing Image row.
            image_store = get_image_store()
            thumbnail_store = get_thumbnail_store()
            for prep in all_successful:
                img_data = prep.get("image_data", {})
                if not img_data.get("reuse_storage_key"):
                    storage_key = img_data.get("storage_key")
                    if storage_key:
                        image_store.delete(storage_key)
                    thumbnail_key = img_data.get("thumbnail_key")
                    if thumbnail_key:
                        thumbnail_store.delete(thumbnail_key)
            for prep in all_successful:
                prep["status"] = "failed"
                prep["error"] = error_info["reason"]
                prep["error_info"] = error_info
                batch_failed += 1
            all_successful = []

    # Batch Qdrant save (only if DB save succeeded)
    warnings: list[dict] = []
    if all_successful and image_ids:
        qdrant_items = [
            {
                "image_id": image_id,
                "embedding": prep["embedding"],
                "metadata": prep["qdrant_metadata"],
            }
            for image_id, prep in zip(image_ids, all_successful, strict=True)
        ]
        qdrant_ok = batch_save_to_qdrant(qdrant_items)
        if not qdrant_ok:
            for prep in all_successful:
                warnings.append(
                    {
                        "filename": Path(prep.get("original_image_path", "unknown")).name,
                        "relative_path": prep.get("relative_path"),
                        "reason": "Saved but may not appear in semantic search until index is rebuilt",
                        "stage": "qdrant_save",
                        "severity": "warning",
                    }
                )

        # Attach image IDs to results
        for prep, image_id in zip(all_successful, image_ids, strict=True):
            prep["image_id"] = image_id

    return prepared_results, batch_failed, warnings


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


def process_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Process a single image end-to-end.

    Thin wrapper around prepare_single_image + single CLIP + single DB/Qdrant save.
    Used for one-off processing; batch flows use the batched pipeline directly.
    """
    logger = logging.getLogger(__name__)
    image_path_obj = Path(image_path)
    logger.info("Processing image: %s", image_path_obj)
    stage = "prepare"

    try:
        # Prepare (thumbnails, colors, copy to store)
        prepared = prepare_single_image(image_path, source_dir=source_dir, metadata=metadata)

        if prepared["status"] != "success":
            return {
                "status": "failed",
                "filepath": image_path,
                "error": prepared.get("error", "Preparation failed"),
            }

        # CLIP embedding (single image)
        stage = "embedding"
        embedding = generate_clip_embedding(image_path)

        # Save to database
        stage = "db_save"
        image_id = save_to_database(prepared["image_data"])

        # Save to Qdrant
        stage = "qdrant_save"
        save_to_qdrant(
            image_id=image_id,
            embedding=embedding,
            metadata=prepared["qdrant_metadata"],
        )

        logger.info("Successfully processed image: %s", image_path_obj)
        return {
            "status": "success",
            "image_id": image_id,
            "filepath": image_path,
        }

    except Exception as e:
        logger.exception("Failed to process image %s", image_path_obj)
        error_info = classify_ingest_error(e, stage=stage)
        return {
            "status": "failed",
            "filepath": image_path,
            "error": error_info["reason"],
        }


def bulk_image_ingestion(
    source_dirs: list[str],
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Ingest images from multiple directories using batched pipeline.

    Images are processed in batches for maximum throughput:
    - prepare_single_image tasks run concurrently via .submit()
    - CLIP embeddings are generated in batch (vectorized forward pass)
    - Database and Qdrant saves are batched into single transactions
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    batch_size = pipeline_config.ingestion_batch_size
    logger.info(
        "Starting bulk ingestion from %s directories (batch_size=%s)", len(source_dirs), batch_size
    )

    successful = 0
    failed = 0
    total_images = 0

    # Build parser once for all images (avoids per-image DB query)
    parser = _build_parser()

    for dir_path in source_dirs:
        directory = Path(dir_path)
        if not directory.exists():
            logger.warning("Directory does not exist: %s", directory)
            continue

        image_paths = scan_directory(dir_path)
        total_images += len(image_paths)

        # Process in batches
        for batch_start in range(0, len(image_paths), batch_size):
            batch = image_paths[batch_start : batch_start + batch_size]
            logger.info(
                "Processing batch %s (%s images, %s/%s)",
                batch_start // batch_size + 1,
                len(batch),
                batch_start + len(batch),
                len(image_paths),
            )

            # Step 1: Prepare images with bounded concurrency to control memory usage.
            prep_pool = get_prepare_pool()
            futures = [
                prep_pool.submit(
                    prepare_single_image,
                    image_path=img_path,
                    source_dir=dir_path,
                    parser=parser,
                    pipeline_config=pipeline_config,
                )
                for img_path in batch
            ]
            prepared_results = _collect_futures(futures)

            # Step 2-4: Batch CLIP → batch DB save → batch Qdrant save
            batch_results, _, _warnings = _process_batch(prepared_results)
            successful += sum(1 for r in batch_results if r["status"] == "success")
            failed += sum(1 for r in batch_results if r["status"] != "success")

    summary = {
        "total_images": total_images,
        "processed": successful + failed,
        "successful": successful,
        "failed": failed,
    }

    # Rebuild FTS index after bulk import
    if successful > 0:
        try:
            with pipeline_db() as db_fts:
                fts_rebuild(db_fts)
                logger.info("FTS index rebuilt after bulk ingestion")
        except Exception as e:
            logger.warning("FTS rebuild failed (non-fatal): %s", e)

    logger.info("Bulk ingestion complete: %s successful, %s failed", successful, failed)
    return summary


def analyse_upload(
    staging_dir: str,
    relative_paths: list[str],
    precomputed_hashes: dict[str, dict] | None = None,
    default_image_type: str = "battlemap",
    file_map: dict[str, str] | None = None,
) -> list[dict]:
    """Parse and group uploaded files for the preview UI.

    Also computes SHA-256 content hashes for each file and checks the
    database for existing images with matching hashes (duplicate detection).

    If ``precomputed_hashes`` is provided (from the client-side pre-flight
    check), those entries skip server-side hash computation and duplicate
    lookup — their content_hash and duplicate_of are used directly.

    ``default_image_type`` is passed to the parser so it can apply
    type-specific parsing rules (e.g. skip grid detection for scenes).

    ``file_map`` maps relative_path → staging_key (UUID filename on disk).
    """
    logger = logging.getLogger(__name__)
    logger.info("Analysing %s uploaded files in %s", len(relative_paths), staging_dir)
    staging = Path(staging_dir)
    if precomputed_hashes is None:
        precomputed_hashes = {}
    if file_map is None:
        file_map = {}

    parser = _build_parser()
    groups = parser.group_files(relative_paths, image_type=default_image_type)

    # Compute content hashes and detect duplicates
    with pipeline_db() as db:
        # Collect hashes that still need DB lookup (non-precomputed files)
        hashes_to_check: dict[str, list[dict]] = {}  # hash -> [file_entry, ...]

        for group in groups:
            for file_entry in group["files"]:
                rel_path = file_entry["relative_path"]
                try:
                    # Use precomputed data if available (from client-side check)
                    precomputed = precomputed_hashes.get(rel_path)
                    if precomputed:
                        file_entry["content_hash"] = precomputed["content_hash"]
                        if precomputed.get("duplicate_of"):
                            file_entry["duplicate_of"] = precomputed["duplicate_of"]
                        continue

                    # Compute hash for files actually in staging
                    staging_key = file_map.get(rel_path, rel_path)
                    file_path = staging / staging_key
                    if not file_path.exists():
                        continue

                    content_hash = _compute_file_hash(file_path)
                    file_entry["content_hash"] = content_hash
                    hashes_to_check.setdefault(content_hash, []).append(file_entry)
                except Exception as e:
                    raise ValueError(f"Failed to analyse '{rel_path}': {e}") from e

        # Batch-query DB for any server-computed hashes
        if hashes_to_check:
            all_hashes = list(hashes_to_check.keys())
            existing_images = db.query(Image).filter(Image.content_hash.in_(all_hashes)).all()
            hash_to_image: dict[str, Image] = {}
            for img in existing_images:
                if img.content_hash and img.content_hash not in hash_to_image:
                    hash_to_image[img.content_hash] = img

            for h, entries in hashes_to_check.items():
                existing = hash_to_image.get(h)
                if existing:
                    dup_info = {
                        "image_id": existing.id,
                        "name": existing.name,
                        "author": existing.author,
                        "storage_key": existing.storage_key,
                        "thumbnail_key": existing.thumbnail_key,
                        "group_name": existing.group_name,
                    }
                    for entry in entries:
                        entry["duplicate_of"] = dup_info
                    logger.info(
                        "  Duplicate detected: %s file(s) match image %s (%s)",
                        len(entries),
                        existing.id,
                        existing.name,
                    )

    logger.info("Detected %s group(s)", len(groups))
    for g in groups:
        logger.info("  %s / %s (%s files)", g.get("author", "?"), g["group_name"], len(g["files"]))

    return groups


# ---------------------------------------------------------------------------
# Shared group-processing helper (used by both single-group and job flows)
# ---------------------------------------------------------------------------


def _run_group(
    group_job_id: str,
    staging_dir: str,
    author: str,
    group_name: str,
    files: list[dict],
    pipeline_config: PipelineConfig | None = None,
    job_id: str | None = None,
    file_map: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Process one group end-to-end and return (processed, failed) counts.

    Updates ImportGroupJob progress after every batch and marks it completed (or
    failed) when done.

    ``file_map`` maps relative_path → staging_key (UUID filename on disk).
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    if file_map is None:
        file_map = {}
    batch_size = pipeline_config.ingestion_batch_size
    concurrency = pipeline_config.max_concurrent_prepare
    staging = Path(staging_dir)
    processed = 0
    failed = 0
    all_file_errors: list[dict] = []

    logger.info(
        "Starting group '%s' by '%s' (%d files, batch_size=%d, concurrency=%d)",
        group_name,
        author,
        len(files),
        batch_size,
        concurrency,
    )

    # Filter to files that exist in staging or have a reuse key (duplicate not uploaded)
    valid_files = []
    for file_info in files:
        staging_key = file_map.get(file_info["relative_path"], file_info["relative_path"])
        image_path = staging / staging_key
        if image_path.exists():
            valid_files.append((file_info, str(image_path)))
        elif file_info.get("reuse_storage_key"):
            # Duplicate not in staging — prepare_single_image only uses
            # image_path_obj.name for the filename in the reuse path
            valid_files.append((file_info, str(image_path)))
        else:
            logger.warning("File not found in staging: %s", file_info["relative_path"])
            failed += 1
            all_file_errors.append(
                {
                    "filename": Path(file_info["relative_path"]).name,
                    "relative_path": file_info["relative_path"],
                    "reason": "File was not found in staging",
                    "stage": "copy",
                    "severity": "error",
                }
            )

    if failed > 0:
        update_import_group_job_progress(
            group_job_id, processed, failed, file_errors=all_file_errors
        )

    try:
        for batch_start in range(0, len(valid_files), batch_size):
            batch = valid_files[batch_start : batch_start + batch_size]
            logger.info(
                "[%s] batch %s (%s images, %s/%s)",
                group_name,
                batch_start // batch_size + 1,
                len(batch),
                batch_start + len(batch),
                len(valid_files),
            )

            # Prepare images with bounded concurrency to control peak memory use.
            _t0 = time.monotonic()
            prep_pool = get_prepare_pool()
            futures = [
                prep_pool.submit(
                    prepare_single_image,
                    image_path=image_path,
                    metadata={
                        "author": author,
                        "group_name": group_name,
                        "name": file_info.get("name") or group_name,
                        "relative_path": file_info.get("relative_path"),
                        "tags": file_info.get("tags", []),
                        "gridded": file_info.get("gridded"),
                        "grid_width": file_info.get("grid_width"),
                        "grid_height": file_info.get("grid_height"),
                        "grid_type": file_info.get("grid_type"),
                        "subgroup": file_info.get("subgroup"),
                        "image_type": file_info.get("image_type", "battlemap"),
                        "content_hash": file_info.get("content_hash"),
                        "media_type": file_info.get("media_type"),
                        "reuse_storage_key": file_info.get("reuse_storage_key"),
                        "reuse_thumbnail_key": file_info.get("reuse_thumbnail_key"),
                        "import_job_id": job_id,
                    },
                    pipeline_config=pipeline_config,
                )
                for file_info, image_path in batch
            ]
            prepared_results = _collect_futures(futures)
            _t_prepare = time.monotonic() - _t0
            logger.info("[%s] prepare took %.1fs", group_name, _t_prepare)

            # Batch CLIP → batch DB → batch Qdrant
            _t0 = time.monotonic()
            batch_results, _, batch_warnings = _process_batch(prepared_results)
            all_file_errors.extend(batch_warnings)
            _t_process = time.monotonic() - _t0
            logger.info("[%s] process_batch took %.1fs", group_name, _t_process)
            batch_success = sum(1 for r in batch_results if r["status"] == "success")
            processed += batch_success
            failed += len(batch_results) - batch_success

            # Collect per-file errors from this batch
            for r in batch_results:
                if r["status"] == "failed":
                    error_info = r.get("error_info", {})
                    rel_path = r.get("relative_path")
                    all_file_errors.append(
                        {
                            "filename": Path(
                                rel_path or r.get("original_image_path", "unknown")
                            ).name,
                            "relative_path": rel_path,
                            "reason": error_info.get("reason", r.get("error", "Unknown error")),
                            "stage": error_info.get("stage", "unknown"),
                            "severity": "error",
                        }
                    )

            update_import_group_job_progress(
                group_job_id, processed, failed, file_errors=all_file_errors
            )

            # Free PIL / numpy / torch objects that survived refcount collection
            gc.collect()
            # Force glibc to return freed pages to the OS.  Without this,
            # Python's pymalloc + glibc malloc retain large arenas even after
            # the Python objects are freed, causing RSS to stay inflated.
            try:
                import ctypes

                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass  # non-Linux or libc unavailable — no-op
            rss_mb = get_rss_mb()
            rss_info = f" — RSS: {rss_mb:.0f} MB" if rss_mb is not None else ""
            logger.info(
                "[%s] batch %d complete%s",
                group_name,
                batch_start // batch_size + 1,
                rss_info,
            )

        # Look up the ImageGroup that was created/updated so we can link back to it
        _created_group_id: int | None = None
        try:
            with pipeline_db() as _db:
                grp = (
                    _db.query(ImageGroup)
                    .filter(ImageGroup.base_name == group_name, ImageGroup.author == author)
                    .first()
                )
                if grp:
                    _created_group_id = grp.id
        except Exception:
            pass  # Non-fatal — link is a convenience, not required

        update_import_group_job_progress(
            group_job_id,
            processed,
            failed,
            status="completed",
            created_group_id=_created_group_id,
            file_errors=all_file_errors,
        )
        warning_count = sum(1 for e in all_file_errors if e.get("severity") == "warning")
        error_count = len(all_file_errors) - warning_count
        logger.info(
            "Group %s (%s): %s ok, %s failed, %s errors, %s warnings",
            group_job_id,
            group_name,
            processed,
            failed,
            error_count,
            warning_count,
        )
    except Exception:
        # Count all files not yet processed as failed, mark group as failed
        remaining = len(valid_files) - processed - failed
        failed += remaining
        logger.exception(
            "Group %s (%s) failed after %s images processed", group_job_id, group_name, processed
        )
        update_import_group_job_progress(
            group_job_id, processed, failed, status="failed", file_errors=all_file_errors
        )
        raise  # re-raise so process_import_job can catch it per-group

    return processed, failed


def _finalize_import_job(job_id: str) -> None:
    """Update ImportJob status after a group finishes processing.

    Delegates to transition_job_status() to auto-complete the job when all
    groups finish.

    If the job was cancelled while a group was still running, performs a
    best-effort cleanup sweep to delete any images added after the initial
    cancel sweep.
    """
    from backend.app.services.import_state import transition_job_status

    logger = logging.getLogger(__name__)
    with pipeline_db() as db:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not job:
            return

        if job.status == "cancelled":
            # Job was cancelled mid-flight — sweep for any images added after the
            # initial cancel (race condition: best-effort cleanup)
            from backend.app.services.deletion_service import (
                cleanup_import_images as _cleanup_import_images,
            )

            swept = _cleanup_import_images(job_id, db)
            if swept:
                logger.info(
                    "Post-cancel sweep: deleted %d late-arriving image(s) for job %s",
                    swept,
                    job_id,
                )
            db.commit()
            return

        new_status = transition_job_status(db, job_id)

        if new_status == "failed":
            # Failed imports must not leave images in the DB — they would
            # cause false duplicate-hash matches when the user re-uploads.
            # Wrapped in try/except so a cleanup failure never blocks the
            # status transition commit.
            try:
                from backend.app.services.deletion_service import (
                    cleanup_import_images as _cleanup_import_images,
                )

                cleaned = _cleanup_import_images(job_id, db)
                if cleaned:
                    logger.info(
                        "Cleaned up %d image(s) from failed import %s",
                        cleaned,
                        job_id,
                    )
            except Exception:
                logger.warning("Image cleanup failed for job %s (non-fatal)", job_id, exc_info=True)

            # Also clean staging — no more groups will run for a failed job.
            staging_dir = settings.staging_dir / job_id
            if staging_dir.exists():
                import shutil

                shutil.rmtree(staging_dir, ignore_errors=True)
                logger.info("Cleaned staging for failed import %s", job_id)

        db.commit()
        logger.info("Import job %s transitioned to '%s'", job_id, new_status)


def _rebuild_fts() -> None:
    """Rebuild the FTS index (non-fatal on error)."""
    logger = logging.getLogger(__name__)
    try:
        with pipeline_db() as db:
            fts_rebuild(db)
        logger.info("FTS index rebuilt successfully")
    except Exception as e:
        logger.warning("FTS rebuild failed (non-fatal): %s", e)


def process_import_group(
    job_id: str,
    group_job_id: str,
    staging_dir: str,
    author: str,
    group_name: str,
    files: list[dict],
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Process a single confirmed group (single-group import path).

    For multi-group imports prefer process_import_job, which handles all groups
    in one Python process so the CLIP model is loaded only once.
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    logger.info(
        "Processing import group '%s' by '%s' (%s files) for job %s, group %s",
        group_name,
        author,
        len(files),
        job_id,
        group_job_id,
    )
    file_map = _load_file_map(Path(staging_dir))
    processed, failed = _run_group(
        group_job_id,
        staging_dir,
        author,
        group_name,
        files,
        pipeline_config=pipeline_config,
        job_id=job_id,
        file_map=file_map,
    )
    _finalize_import_job(job_id)
    if processed > 0:
        _rebuild_fts()

    # Staging cleanup is handled by /cancel, or expire_stale_jobs —
    # NOT here, because other groups in the same job may still be pending.

    return {
        "job_id": job_id,
        "group_job_id": group_job_id,
        "processed": processed,
        "failed": failed,
        "total": len(files),
    }


def process_import_job(
    job_id: str,
    staging_dir: str,
    groups: list[dict],
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Process all groups for an import job in a single flow run.

    Running all groups here — rather than one flow per group — means the CLIP
    model (~600 MB) is loaded exactly once for the whole job instead of once
    per group in separate subprocesses.  Groups are processed sequentially so
    peak memory stays bounded regardless of how many groups are in the job.

    Each group dict must contain:
        group_job_id, author, group_name, files (list[dict])

    Groups are isolated: an unhandled exception in one group is caught, the
    group is marked as failed, and processing continues with the next group.
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    logger.info("Starting import job %s: %s group(s) in %s", job_id, len(groups), staging_dir)
    file_map = _load_file_map(Path(staging_dir))
    total_processed = 0
    total_failed = 0

    try:
        for group in groups:
            group_job_id = group["group_job_id"]
            author = group["author"]
            group_name = group["group_name"]
            files = group["files"]
            logger.info("Processing group '%s' by '%s' (%s files)", group_name, author, len(files))
            try:
                processed, failed = _run_group(
                    group_job_id,
                    staging_dir,
                    author,
                    group_name,
                    files,
                    pipeline_config=pipeline_config,
                    job_id=job_id,
                    file_map=file_map,
                )
                total_processed += processed
                total_failed += failed
            except Exception as e:
                # _run_group already updated the group job status to "failed".
                # We log the error, count all unprocessed files as failed, and
                # continue with the next group so the job doesn't abort early.
                logger.error(
                    "Group '%s' (%s) raised an unhandled exception, skipping to next group: %s",
                    group_name,
                    group_job_id,
                    e,
                )
                total_failed += len(files)
    finally:
        # Always finalize the job and rebuild FTS — even if some groups raised
        # unexpected exceptions.  Staging cleanup is handled by /cancel,
        # or expire_stale_jobs.
        _finalize_import_job(job_id)
        if total_processed > 0:
            _rebuild_fts()

    logger.info(
        "Import job %s complete: %s processed, %s failed", job_id, total_processed, total_failed
    )
    return {
        "job_id": job_id,
        "processed": total_processed,
        "failed": total_failed,
        "total_groups": len(groups),
    }
