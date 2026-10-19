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

from sqlalchemy.orm import joinedload, selectinload

from backend.app.models.database import Image
from backend.app.services.originals import OriginalUnavailable, original_path
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline.db import pipeline_db
from backend.pipeline.naming import export_metadata, unique_export_path

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def export_library(output_dir: str, progress_fn=None) -> dict:
    """Copy all images into *output_dir* with human-readable names.

    Compatible with the JobRunner ``progress_fn`` injection convention:
        progress_fn(current: int, total: int, message: str)

    Returns a summary dict: {total, exported, skipped, output_dir}.
    """
    with pipeline_db() as db:
        all_ids = [row[0] for row in db.query(Image.id).order_by(Image.id).all()]
    total = len(all_ids)

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)

    seen_paths: set[str] = set()
    metadata: dict[str, dict] = {}
    exported = 0
    skipped = 0

    for i in range(0, total, BATCH_SIZE):
        raise_if_shutting_down()
        batch_ids = all_ids[i : i + BATCH_SIZE]

        # The rows are read inside the session: pipeline_db commits on exit, which
        # expires them.
        with pipeline_db() as db:
            batch = (
                db.query(Image)
                .options(
                    joinedload(Image.tags),
                    joinedload(Image.group),
                    selectinload(Image.source_file),
                )
                .filter(Image.id.in_(batch_ids))
                .all()
            )
            for img in batch:
                try:
                    source = original_path(img)
                except OriginalUnavailable as exc:
                    logger.warning("Export: skipped image %d: %s", img.id, exc.reason)
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
