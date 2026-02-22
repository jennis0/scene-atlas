"""Re-parse variant group names and image names using the improved parser.

Applies _clean_group_name to all VariantGroup.base_name values and
_build_map_name to all Image.name values, then rebuilds search_text
and the FTS index.

Usage:
    uv run python -m backend.flows.reparse_names
"""

import logging
import os
from pathlib import Path

from prefect import flow, task

os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

from backend.app.config import settings
from backend.app.models.database import (
    Image,
    TagCategory,
    VariantGroup,
    get_engine,
    get_session_local,
)
from backend.app.services import BattlemapParser
from backend.app.services.battlemap_parser import build_search_text
from backend.app.services.fts_service import fts_rebuild

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def _build_parser(db) -> BattlemapParser:
    """Create a BattlemapParser with tag vocabulary loaded from DB."""
    categories = db.query(TagCategory).all()
    cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
    return BattlemapParser(tag_categories=cat_dicts)


@task(name="clean_variant_group_names")
def clean_variant_group_names(parser: BattlemapParser) -> dict:
    """Clean all VariantGroup base_name values.

    Returns mapping of VG id -> new base_name for use by the image task.
    """
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    updated = 0
    unchanged = 0
    vg_names: dict[int, str] = {}

    try:
        groups = db.query(VariantGroup).all()
        for vg in groups:
            cleaned = parser._clean_group_name(vg.base_name, vg.author)
            vg_names[vg.id] = cleaned
            if cleaned != vg.base_name:
                vg.base_name = cleaned
                updated += 1
            else:
                unchanged += 1
        db.commit()
    finally:
        db.close()

    print(f"Variant groups: {updated} updated, {unchanged} unchanged")
    return vg_names


@task(name="reparse_image_names_batch")
def reparse_image_names_batch(
    image_ids: list[int],
    parser: BattlemapParser,
    vg_names: dict[int, str],
) -> dict:
    """Re-parse names for a batch of images."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    updated = 0
    unchanged = 0
    errors = 0

    try:
        images = db.query(Image).filter(Image.id.in_(image_ids)).all()
        for image in images:
            try:
                stem = Path(image.filename).stem
                vg_name = vg_names.get(image.variant_group_id, "")
                sub_variants = (
                    image.sub_variant.split(" / ") if image.sub_variant else []
                )
                new_name = parser._build_map_name(
                    stem, image.author, vg_name, sub_variants
                )

                name_changed = new_name != image.name
                if name_changed:
                    image.name = new_name

                # Rebuild search_text with the (possibly new) name
                tags = [
                    {"category": t.category, "value": t.value} for t in image.tags
                ]
                new_search_text = build_search_text(
                    name=image.name,
                    filename=image.filename,
                    author=image.author,
                    tags=tags,
                    sub_variant=image.sub_variant,
                )
                search_changed = new_search_text != image.search_text
                if search_changed:
                    image.search_text = new_search_text

                if name_changed or search_changed:
                    updated += 1
                else:
                    unchanged += 1
            except Exception as e:
                logger.error(f"Image {image.id}: error reparsing name: {e}")
                errors += 1

        db.commit()
    finally:
        db.close()

    return {"updated": updated, "unchanged": unchanged, "errors": errors}


@flow(name="reparse_names", log_prints=True)
def reparse_names():
    """Re-parse all variant group and image names using the improved parser."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        parser = _build_parser(db)

        # Collect all image IDs upfront
        all_ids = [row[0] for row in db.query(Image.id).order_by(Image.id).all()]
    finally:
        db.close()

    total = len(all_ids)
    print(f"Re-parsing names for {total} images")

    if total == 0:
        print("Nothing to reparse")
        return {"total": 0, "updated": 0, "unchanged": 0, "errors": 0}

    # Step 1: Clean variant group names
    vg_names = clean_variant_group_names(parser)

    # Step 2: Re-parse image names in batches
    # vg_names keys are int from SQLAlchemy, but dict keys survive Prefect
    totals = {"updated": 0, "unchanged": 0, "errors": 0}
    for i in range(0, total, BATCH_SIZE):
        batch_ids = all_ids[i : i + BATCH_SIZE]
        result = reparse_image_names_batch(batch_ids, parser, vg_names)
        totals["updated"] += result["updated"]
        totals["unchanged"] += result["unchanged"]
        totals["errors"] += result["errors"]
        print(f"  Processed {min(i + BATCH_SIZE, total)}/{total}")

    # Step 3: Rebuild FTS index
    if totals["updated"] > 0:
        print("Rebuilding FTS index...")
        try:
            engine = get_engine(settings.database_url)
            SessionLocal = get_session_local(engine)
            db = SessionLocal()
            try:
                fts_rebuild(db)
                print("FTS index rebuilt successfully")
            finally:
                db.close()
        except Exception as e:
            print(f"FTS rebuild failed (non-fatal): {e}")

    print(f"Reparse complete: {totals}")
    return {"total": total, **totals}


if __name__ == "__main__":
    reparse_names()
