"""Export the image library to a human-readable directory tree.

Copies every image from the content-addressed store into an organised
folder structure:

    <output_dir>/
      metadata.json
      Author/
        Group/
          [Subgroup/]
            Group - [Subgroup - ]Name - Grid WxH.ext
        _Ungrouped/
          Name - No Grid.ext

Usage:
    uv run python -m backend.pipeline.export_library [output_dir]

If ``output_dir`` is omitted, files are written to
``data/exports/<YYYYMMDD_HHMMSS>/``.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from backend.app.config import settings
from backend.app.models.database import Image, get_engine, get_session_local
from backend.app.services import get_image_store
from backend.pipeline.naming import export_metadata, unique_export_path

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def export_library(output_dir: str, progress_fn=None) -> dict:
    """Copy all images into *output_dir* with human-readable names.

    Compatible with the JobRunner ``progress_fn`` injection convention:
        progress_fn(current: int, total: int, message: str)

    Returns a summary dict: {total, exported, skipped, output_dir}.
    """
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        all_ids = [row[0] for row in db.query(Image.id).order_by(Image.id).all()]
        total = len(all_ids)
    finally:
        db.close()

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)

    image_store = get_image_store()
    seen_paths: set[str] = set()
    metadata: dict[str, dict] = {}
    exported = 0
    skipped = 0

    for i in range(0, total, BATCH_SIZE):
        batch_ids = all_ids[i : i + BATCH_SIZE]

        db = SessionLocal()
        try:
            from sqlalchemy.orm import joinedload

            batch = (
                db.query(Image)
                .options(joinedload(Image.tags), joinedload(Image.group))
                .filter(Image.id.in_(batch_ids))
                .all()
            )
        finally:
            db.close()

        for img in batch:
            source = image_store.get_path(img.storage_key)
            if not source or not source.exists():
                logger.warning("Export: missing file for image %d", img.id)
                skipped += 1
                continue

            arc = unique_export_path(img, seen_paths)

            target = dest / arc
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

            metadata[arc] = export_metadata(img)
            exported += 1

        processed = min(i + BATCH_SIZE, total)
        msg = f"Exported {processed}/{total}"
        logger.info(msg)
        if progress_fn:
            progress_fn(processed, total, msg)

    meta_payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": 1,
        "total_images": exported,
        "images": metadata,
    }
    (dest / "metadata.json").write_text(
        json.dumps(meta_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("Export complete: %d exported, %d skipped → %s", exported, skipped, dest)
    return {"total": total, "exported": exported, "skipped": skipped, "output_dir": str(dest)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) > 1:
        out = sys.argv[1]
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(Path("data/exports") / stamp)

    print(f"Exporting library to: {out}")
    result = export_library(out)
    print(f"Done. Exported {result['exported']} image(s), skipped {result['skipped']}.")
