"""Image preparation: parsing, copying, thumbnails, colors, grid detection.

Single-image preparation without database or embedding operations.
Designed to run concurrently via ThreadPoolExecutor in the pipeline.

Functions:
    prepare_single_image — Main: parse, copy, thumbnails, colors for one image
    _build_parser        — Create ImageParser with tag vocabulary
    _compute_file_hash   — Compute SHA-256 hash for duplicate detection
    scan_directory       — Find all supported image files in directory tree
    _collect_futures     — Collect concurrent task results with cleanup
"""

import hashlib
import logging
import uuid
from pathlib import Path

from backend.app.config import settings
from backend.app.models import Image, TagCategory
from backend.app.services import ImageParser, get_image_store, get_thumbnail_store

from .db import pipeline_db
from .error_classifier import classify_ingest_error
from .pipeline_config import PipelineConfig


def _build_parser() -> ImageParser:
    """Create an ImageParser with tag vocabulary loaded from DB."""
    with pipeline_db() as db:
        categories = db.query(TagCategory).all()
        cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
        return ImageParser(tag_categories=cat_dicts)


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file, reading in 8KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _collect_futures(futures: list) -> list:
    """Collect future results, cancelling all on exception.

    Must collect ALL futures even on error — abandoning futures leaks work
    into the shared pool. This helper ensures consistent error handling.
    """
    try:
        return [f.result() for f in futures]
    except Exception:
        for f in futures:
            f.cancel()
        raise


def scan_directory(directory: str) -> list[str]:
    """Scan directory for supported image files."""
    logger = logging.getLogger(__name__)
    directory_obj = Path(directory)
    logger.info("Scanning directory: %s", directory_obj)
    image_paths = []

    for ext in settings.all_supported_formats:
        for path in directory_obj.rglob(f"*{ext}"):
            if "__MACOSX" in path.parts or path.name.startswith("._"):
                continue
            image_paths.append(str(path))

    logger.info("Found %s images/videos in %s", len(image_paths), directory_obj)
    return image_paths


def prepare_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
    parser: ImageParser | None = None,
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Prepare a single image: parse metadata, copy to store, thumbnails, colors.

    This task handles everything EXCEPT CLIP embedding and database/Qdrant saves,
    which are batched separately for better throughput.

    Runs inline (not sub-tasks) for minimal overhead when submitted concurrently.

    Args:
        image_path: Absolute path to the image file
        source_dir: Root directory for relative path parsing (CLI mode)
        metadata: Explicit metadata dict (web import mode)
        parser: Pre-built ImageParser (avoids rebuilding per image in batch)

    Returns:
        Dict with 'status', 'image_data', 'original_image_path', 'qdrant_metadata'
    """
    logger = logging.getLogger(__name__)
    image_path_obj = Path(image_path)
    logger.info("Preparing image: %s", image_path_obj.name)

    stage = "parse"
    relative_path = None
    try:
        # --- Parse metadata ---
        if metadata:
            author = metadata.get("author")
            group_name = metadata.get("group_name")
            name = metadata.get("name") or group_name
            subgroup = metadata.get("subgroup")
            image_type = metadata.get("image_type", "battlemap")
            gridded = metadata.get("gridded")
            grid_width = metadata.get("grid_width")
            grid_height = metadata.get("grid_height")
            grid_type = metadata.get("grid_type")
            tags = metadata.get("tags", [])
            content_hash = metadata.get("content_hash")
            reuse_storage_key = metadata.get("reuse_storage_key")
            reuse_thumbnail_key = metadata.get("reuse_thumbnail_key")
            relative_path = metadata.get("relative_path")
            import_job_id = metadata.get("import_job_id")
            # Resolve original filename: staging paths use UUID hex names,
            # so we derive the human-readable filename from relative_path.
            original_filename = Path(relative_path).name if relative_path else image_path_obj.name
        else:
            if parser is None:
                parser = _build_parser()
            source_dir_obj = Path(source_dir) if source_dir else None
            if source_dir_obj:
                relative = image_path_obj.relative_to(source_dir_obj)
            else:
                relative = Path(image_path_obj.name)
            parsed = parser.parse(str(relative))
            author = parsed["author"]
            group_name = parsed["group_name"]
            name = parsed.get("name") or group_name
            subgroup = parsed["subgroup"]
            image_type = parsed.get("image_type", "battlemap")
            gridded = parsed["gridded"]
            grid_width = parsed["grid_width"]
            grid_height = parsed["grid_height"]
            grid_type = parsed.get("grid_type")
            tags = parsed["tags"]
            content_hash = None
            reuse_storage_key = None
            reuse_thumbnail_key = None
            relative_path = str(relative)
            import_job_id = None
            original_filename = image_path_obj.name

        # --- Duplicate reuse path ---
        # If we're reusing an existing file, skip copy/thumbnail/color extraction
        # and copy properties from the existing image record instead.
        if reuse_storage_key:
            image_store = get_image_store()
            if not image_store.get_path(reuse_storage_key).exists():
                logger.warning(
                    "Reuse key %s not found on disk, falling back to normal path", reuse_storage_key
                )
                reuse_storage_key = None  # Fall through to normal path below

        if reuse_storage_key:
            # Look up existing image to copy dimensions, file_size, colors
            with pipeline_db() as db:
                source_image = (
                    db.query(Image).filter(Image.storage_key == reuse_storage_key).first()
                )
                if source_image:
                    width = source_image.width
                    height = source_image.height
                    file_size = source_image.file_size
                    colors = [
                        {
                            "color_hex": c.color_hex,
                            "percentage": c.percentage,
                            "color_order": c.color_order,
                        }
                        for c in source_image.colors
                    ]
                    reuse_embedding_from = source_image.id
                else:
                    # Source record gone — fall back to computing from file
                    logger.warning("No DB record for storage_key=%s", reuse_storage_key)
                    reuse_storage_key = None

        if reuse_storage_key:
            reuse_ext = image_path_obj.suffix.lower()
            image_data = {
                "filename": original_filename,
                "storage_key": reuse_storage_key,
                "name": name,
                "author": author,
                "group_name": group_name,
                "width": width,
                "height": height,
                "file_size": file_size,
                "thumbnail_key": reuse_thumbnail_key,
                "gridded": gridded,
                "grid_width": grid_width,
                "grid_height": grid_height,
                "grid_type": metadata.get("grid_type") if metadata else None,
                "grid_confidence": metadata.get("grid_confidence") if metadata else None,
                "subgroup": subgroup,
                "image_type": image_type,
                "content_hash": content_hash,
                "media_type": "video" if reuse_ext in settings.supported_video_formats else "image",
                "tags": tags,
                "colors": colors,
                "import_job_id": import_job_id,
            }

            qdrant_metadata = {
                "filename": original_filename,
                "author": author,
                "base_name": group_name,
            }

            return {
                "status": "success",
                "image_data": image_data,
                "original_image_path": image_path,
                "qdrant_metadata": qdrant_metadata,
                "reuse_embedding_from": reuse_embedding_from,
            }

        # --- Normal path: Copy image/video into ImageStore ---
        stage = "copy"
        image_store = get_image_store()
        storage_key_stem = uuid.uuid4().hex[:12]
        ext = image_path_obj.suffix.lower()
        storage_key = f"{storage_key_stem}{ext}"
        image_store.put(storage_key, image_path_obj)

        # Compute content hash if not already known
        if not content_hash:
            content_hash = _compute_file_hash(image_path_obj)

        # --- File size (inline, fast) ---
        file_size = image_path_obj.stat().st_size

        # --- Generate thumbnails + get dimensions ---
        # --- Extract colors ---
        stage = "thumbnails"
        from backend.pipeline.tasks.color_extraction import (
            extract_dominant_colors as _extract_colors,
        )
        from backend.pipeline.tasks.image_processing import generate_thumbnails as _gen_thumbs

        is_video = ext in settings.supported_video_formats

        if is_video:
            # Extract first frame to a temp JPEG for thumbnail/color/CLIP processing
            from backend.app.services.video_utils import extract_first_frame, get_video_dimensions

            frame_img = extract_first_frame(image_path_obj)
            frame_path = image_path_obj.parent / f".{storage_key_stem}_frame.jpg"
            frame_img.save(str(frame_path), format="JPEG", quality=95)
            frame_img.close()

            thumbnail_result = _gen_thumbs(str(frame_path), storage_key_stem)
            thumbnail_keys = thumbnail_result["keys"]
            stage = "colors"
            colors = _extract_colors(str(frame_path), pipeline_config=pipeline_config)
            width, height = get_video_dimensions(image_path_obj)
            clip_image_path = str(frame_path)  # keep alive for CLIP in _process_batch
        else:
            thumbnail_result = _gen_thumbs(image_path, storage_key_stem)
            thumbnail_keys = thumbnail_result["keys"]
            stage = "colors"
            colors = _extract_colors(image_path, pipeline_config=pipeline_config)
            width, height = thumbnail_result["dimensions"]
            clip_image_path = None

        thumbnail_key = thumbnail_keys.get("medium", thumbnail_keys.get("small"))

        # Use the medium (or small) thumbnail as the CLIP encoding source.
        # CLIP resizes to 224×224 internally, so opening full-res originals is wasteful.
        # Thumbnails are ~470KB vs potentially 50-200MB for originals.
        # clip_image_path retains its original meaning: temp video frame to clean up after CLIP.
        if is_video:
            clip_source_path = str(frame_path)  # same file as clip_image_path
        else:
            clip_source_path = (
                str(get_thumbnail_store().get_path(thumbnail_key)) if thumbnail_key else None
            )

        # --- Image-based grid detection (optional, battlemaps only) ---
        stage = "grid_detection"
        # grid_type is already set from metadata or filename parsing above.
        # Image-based detection can override it if it produces a result.
        grid_confidence = None

        _cfg = pipeline_config  # may be None — detect_grid_from_image handles both
        _grid_enabled = (
            _cfg.enable_image_grid_detection
            if _cfg is not None
            else False  # safe default; callers should always pass a config
        )

        if _grid_enabled and image_type == "battlemap" and not is_video:
            from backend.pipeline.tasks.grid_detection import (
                detect_grid_from_image as _detect_grid,
            )

            if gridded is None:
                # No filename hint — detect presence + size
                grid_result = _detect_grid(
                    image_path, width, height, size_only=False, pipeline_config=_cfg
                )
            elif gridded is True and grid_width is None:
                # Filename says gridded but no dimensions — detect size only
                grid_result = _detect_grid(
                    image_path, width, height, size_only=True, pipeline_config=_cfg
                )
            else:
                grid_result = None

            if grid_result and grid_result.get("confidence", 0) > 0:
                if gridded is None:
                    gridded = grid_result.get("gridded")
                if grid_result.get("grid_width") is not None:
                    grid_width = grid_result["grid_width"]
                    grid_height = grid_result["grid_height"]
                grid_type = grid_result.get("grid_type")
                grid_confidence = grid_result.get("confidence")

        # --- Build result ---
        image_data = {
            "filename": original_filename,
            "storage_key": storage_key,
            "name": name,
            "author": author,
            "group_name": group_name,
            "width": width,
            "height": height,
            "file_size": file_size,
            "thumbnail_key": thumbnail_key,
            "gridded": gridded,
            "grid_width": grid_width,
            "grid_height": grid_height,
            "grid_type": grid_type,
            "grid_confidence": grid_confidence,
            "subgroup": subgroup,
            "image_type": image_type,
            "content_hash": content_hash,
            "media_type": "video" if is_video else "image",
            "tags": tags,
            "colors": colors,
            "import_job_id": import_job_id,
        }

        qdrant_metadata = {
            "filename": original_filename,
            "author": author,
            "base_name": group_name,
        }

        return {
            "status": "success",
            "image_data": image_data,
            "original_image_path": image_path,
            "relative_path": relative_path,
            "clip_image_path": clip_image_path,  # None for images, temp frame path for videos (cleanup only)
            "clip_source_path": clip_source_path,  # thumbnail path for CLIP encoding (avoids full-res loads)
            "qdrant_metadata": qdrant_metadata,
        }

    except Exception as e:
        logger.exception("Failed to prepare image %s at stage '%s'", image_path_obj, stage)
        error_info = classify_ingest_error(e, stage=stage)
        return {
            "status": "failed",
            "original_image_path": image_path,
            "relative_path": relative_path,
            "error": error_info["reason"],
            "error_info": error_info,
        }
