"""Re-parse group names and image names using the improved parser.

Applies clean_group_name to all ImageGroup.base_name values and
_build_name to all Image.name values, then rebuilds search_text
and the FTS index.

Usage:
    uv run python -m backend.pipeline.reparse_names
"""

import logging
from pathlib import Path

from backend.app.models.database import Image, ImageGroup
from backend.app.services import ImageParser
from backend.app.services.fts_service import fts_rebuild
from backend.app.services.image_parser import build_search_text
from backend.app.services.shutdown import raise_if_shutting_down
from backend.pipeline.db import pipeline_db
from backend.pipeline.ingest_queue import build_parser

BATCH_SIZE = 200


def clean_group_names(parser: ImageParser) -> dict[int, str]:
    """Clean all ImageGroup base_name values.

    Returns mapping of group id -> new base_name for use by the image task.
    """
    updated = 0
    unchanged = 0
    group_names: dict[int, str] = {}

    with pipeline_db() as db:
        groups = db.query(ImageGroup).all()
        for grp in groups:
            cleaned = parser.clean_group_name(grp.base_name, grp.author)
            group_names[grp.id] = cleaned
            if cleaned != grp.base_name:
                grp.base_name = cleaned
                updated += 1
            else:
                unchanged += 1

    print(f"Groups: {updated} updated, {unchanged} unchanged")
    return group_names


def reparse_image_names_batch(
    image_ids: list[int],
    parser: ImageParser,
    group_names: dict[int, str],
) -> dict:
    """Re-parse names for a batch of images."""
    updated = 0
    unchanged = 0
    errors = 0

    with pipeline_db() as db:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                stem = Path(image.filename).stem
                grp_name = group_names.get(image.group_id, "") if image.group_id else ""
                subgroups = image.subgroup.split(" / ") if image.subgroup else []
                new_name = parser._build_name(stem, image.author, grp_name, subgroups)

                name_changed = new_name != image.name
                if name_changed:
                    image.name = new_name

                # Rebuild search_text with the (possibly new) name
                tags = [{"category": t.category, "value": t.value} for t in image.tags]
                new_search_text = build_search_text(
                    name=image.name,
                    filename=image.filename,
                    author=image.author,
                    tags=tags,
                    subgroup=image.subgroup,
                )
                search_changed = new_search_text != image.search_text
                if search_changed:
                    image.search_text = new_search_text

                if name_changed or search_changed:
                    updated += 1
                else:
                    unchanged += 1
            except Exception:
                logging.getLogger(__name__).exception("Image %s: error reparsing name", image.id)
                errors += 1

    return {"updated": updated, "unchanged": unchanged, "errors": errors}


def reparse_names():
    """Re-parse all group and image names using the improved parser."""
    with pipeline_db() as db:
        parser = build_parser(db)

        # Collect all image IDs upfront
        all_ids = [row[0] for row in db.query(Image.id).order_by(Image.id).all()]

    total = len(all_ids)
    print(f"Re-parsing names for {total} images")

    if total == 0:
        print("Nothing to reparse")
        return {"total": 0, "updated": 0, "unchanged": 0, "errors": 0}

    # Step 1: Clean group names
    group_names = clean_group_names(parser)

    # Step 2: Re-parse image names in batches
    totals = {"updated": 0, "unchanged": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        raise_if_shutting_down()
        batch_ids = all_ids[i : i + BATCH_SIZE]
        result = reparse_image_names_batch(batch_ids, parser, group_names)
        totals["updated"] += result["updated"]
        totals["unchanged"] += result["unchanged"]
        totals["errors"] += result["errors"]
        print(f"  Processed {min(i + BATCH_SIZE, total)}/{total}")

    # Step 3: Rebuild FTS index
    if totals["updated"] > 0:
        print("Rebuilding FTS index...")
        try:
            with pipeline_db() as db:
                fts_rebuild(db)
            print("FTS index rebuilt successfully")
        except Exception as e:
            print(f"FTS rebuild failed (non-fatal): {e}")

    print(f"Reparse complete: {totals}")
    return {"total": total, **totals}


if __name__ == "__main__":
    reparse_names()
