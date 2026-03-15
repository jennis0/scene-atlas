"""Tag pack import service — merge genre-specific tag packs into the database."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ..data.vocabulary import (
    build_common_values_json,
    get_available_packs,
    get_pack_metadata,
    get_tags_for_packs,
)
from ..models.database import TagCategory

logger = logging.getLogger(__name__)


def get_pack_status(session: Session) -> list[dict]:
    """Return status of each tag pack: metadata, tag count, and import state.

    A pack is considered "imported" when all its tag values are present
    in the corresponding category's common_values.
    """
    pack_meta = get_pack_metadata()
    packs = get_available_packs()

    # Load all current categories from DB
    db_categories: dict[str, TagCategory] = {
        cat.name: cat for cat in session.query(TagCategory).all()
    }

    result = []
    for pack_name in packs:
        meta = pack_meta[pack_name]
        pack_categories = get_tags_for_packs([pack_name])

        total_tags = sum(len(cat["tags"]) for cat in pack_categories)
        existing_tags = 0

        for cat_data in pack_categories:
            db_cat = db_categories.get(cat_data["name"])
            if not db_cat:
                continue
            db_values = _parse_existing_values(db_cat.common_values)
            for tag in cat_data["tags"]:
                if tag["value"] in db_values:
                    existing_tags += 1

        result.append(
            {
                "name": pack_name,
                "label": meta["label"],
                "description": meta["description"],
                "tag_count": total_tags,
                "imported": existing_tags == total_tags,
                "new_tags": total_tags - existing_tags,
            }
        )

    return result


def import_tag_pack(session: Session, pack_name: str) -> dict[str, int]:
    """Merge a tag pack into the database vocabulary.

    For each category in the pack:
    - Creates the category if it doesn't exist
    - Appends new tag values (existing values are preserved)
    - Unions new aliases into existing tag entries

    Returns counts of changes made.
    """
    if pack_name not in get_available_packs():
        raise ValueError(f"Unknown tag pack: {pack_name}")

    pack_categories = get_tags_for_packs([pack_name])

    categories_created = 0
    tags_added = 0
    tags_existing = 0

    for cat_data in pack_categories:
        db_cat = session.query(TagCategory).filter(TagCategory.name == cat_data["name"]).first()

        if not db_cat:
            # Create the category with only this pack's tags
            db_cat = TagCategory(
                name=cat_data["name"],
                description=cat_data["description"],
                color=cat_data["color"],
                icon=cat_data.get("icon"),
                display_order=cat_data["display_order"],
                common_values=build_common_values_json(cat_data["tags"]),
            )
            session.add(db_cat)
            categories_created += 1
            tags_added += len(cat_data["tags"])
            continue

        # Merge into existing category
        existing = _parse_existing_values(db_cat.common_values)
        current_entries = json.loads(db_cat.common_values or "[]")

        for tag in cat_data["tags"]:
            if tag["value"] in existing:
                # Union aliases
                _merge_aliases(current_entries, tag["value"], tag["aliases"])
                tags_existing += 1
            else:
                # Append new tag
                if tag["aliases"]:
                    current_entries.append({"value": tag["value"], "aliases": tag["aliases"]})
                else:
                    current_entries.append(tag["value"])
                tags_added += 1

        db_cat.common_values = json.dumps(current_entries)

    session.commit()

    # Invalidate alias cache so the parser picks up new vocabulary
    from ..services.fts_service import invalidate_alias_cache

    invalidate_alias_cache()

    logger.info(
        "Imported tag pack '%s': %d created, %d added, %d existing",
        pack_name,
        categories_created,
        tags_added,
        tags_existing,
    )

    return {
        "categories_created": categories_created,
        "tags_added": tags_added,
        "tags_existing": tags_existing,
    }


def _parse_existing_values(common_values_json: str | None) -> set[str]:
    """Extract canonical tag values from a common_values JSON string."""
    if not common_values_json:
        return set()
    entries = json.loads(common_values_json)
    return {e if isinstance(e, str) else e["value"] for e in entries}


def _merge_aliases(entries: list, value: str, new_aliases: list[str]) -> None:
    """Union new aliases into an existing entry's alias list."""
    if not new_aliases:
        return
    for i, entry in enumerate(entries):
        canonical = entry if isinstance(entry, str) else entry["value"]
        if canonical != value:
            continue

        if isinstance(entry, str):
            # Convert to object form to add aliases
            entries[i] = {"value": value, "aliases": list(new_aliases)}
        else:
            existing_aliases = set(entry.get("aliases", []))
            merged = existing_aliases | set(new_aliases)
            entry["aliases"] = sorted(merged)
        return
