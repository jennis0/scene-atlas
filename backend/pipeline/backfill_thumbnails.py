"""Make the thumbnails of images whose thumbnail file is missing, from their originals.

After a rebuild (design/export-backup-move.md §8): from an older export the rows name
thumbnails this app data never had, and when the app data was lost there are none at all.
Until then the gallery falls back to the full-size originals, which works, slowly.

Usage:
    uv run python -m backend.pipeline.backfill_thumbnails
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image as PILImage
from sqlalchemy import select

from backend.app.models.database import Image
from backend.app.services import get_thumbnail_store
from backend.app.services.originals import original_path
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline.db import pipeline_db
from backend.pipeline.tasks.image_processing import write_thumbnails

logger = logging.getLogger(__name__)

JOB_NAME = "Making thumbnails"
_BATCH = 200
_SIZE_SUFFIX = re.compile(r"_\d+x\d+$")

ProgressFn = Callable[[int, int, str | None], None]


def _stem(thumbnail_key: str | None) -> str:
    """The stem the image's thumbnails share (``<stem>_<w>x<h>.jpg``), or a new one."""
    if thumbnail_key:
        return _SIZE_SUFFIX.sub("", Path(thumbnail_key).stem)
    return uuid.uuid4().hex


def _page(after: int) -> list[tuple[int, str | None]]:
    """The next images' ids and thumbnail keys, in id order."""
    with pipeline_db() as db:
        return list(
            db.execute(
                select(Image.id, Image.thumbnail_key)
                .where(Image.id > after)
                .order_by(Image.id)
                .limit(_BATCH)
            ).tuples()
        )


def _make(image: Image, work: Path) -> str:
    """Write *image*'s thumbnails into the store; returns its thumbnail key (medium)."""
    source = original_path(image)
    if image.media_type == "video":
        from backend.app.services.video_utils import extract_first_frame

        picture = extract_first_frame(source)
    else:
        picture = PILImage.open(source)
        picture.draft("RGB", (1600, 1600))  # a large JPEG decodes at a reduced scale
        picture.load()
    try:
        made = write_thumbnails(picture, _stem(image.thumbnail_key), work)
    finally:
        picture.close()
    store = get_thumbnail_store()
    for key, path in made.values():
        target = store.get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, target)
    return made["medium"][0]


def backfill_thumbnails(progress_fn: ProgressFn | None = None) -> dict:
    """Make every missing thumbnail. An image whose original can't be read is skipped and
    counted (the gallery shows the original, or its usual placeholder)."""
    made = skipped = 0
    after = 0
    with tempfile.TemporaryDirectory(prefix="sa-thumbs-") as tmp:
        work = Path(tmp)
        store = get_thumbnail_store()
        while True:
            raise_if_shutting_down()
            page = _page(after)
            if not page:
                break
            after = page[-1][0]
            todo = [i for i, key in page if not (key and store.get_path(key).is_file())]
            if not todo:
                continue
            with pipeline_db() as db:
                for image_id in todo:
                    raise_if_shutting_down()
                    image = db.get(Image, image_id)
                    if image is None:
                        continue
                    try:
                        image.thumbnail_key = _make(image, work)
                        made += 1
                    except Exception as exc:  # one bad original (a decompression bomb) is skipped
                        skipped += 1
                        logger.warning("Thumbnail for image %d not made: %s", image_id, exc)
                db.commit()
            if progress_fn:
                progress_fn(made + skipped, 0, f"Made {made:,} thumbnails")
    logger.info("Thumbnails: %d made, %d skipped", made, skipped)
    return {"made": made, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(backfill_thumbnails())
