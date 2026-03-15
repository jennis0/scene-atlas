"""Loader for the tag vocabulary JSON file.

Provides functions to read the canonical tag vocabulary, filter by pack,
and convert to the common_values JSON format used in the database.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_VOCAB_PATH = Path(__file__).parent / "tag_vocabulary.json"


@lru_cache(maxsize=1)
def load_vocabulary() -> dict[str, Any]:
    """Read and parse the tag vocabulary JSON file."""
    with _VOCAB_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_pack_metadata() -> dict[str, dict[str, str]]:
    """Return pack definitions with label and description."""
    return load_vocabulary()["packs"]


def get_available_packs() -> list[str]:
    """Return list of available pack names."""
    return list(load_vocabulary()["packs"].keys())


def get_tags_for_packs(pack_names: list[str]) -> list[dict[str, Any]]:
    """Filter vocabulary to only tags belonging to the specified packs.

    Returns category dicts with only matching tags included.
    Categories with no matching tags are omitted.
    """
    vocab = load_vocabulary()
    pack_set = set(pack_names)
    result = []

    for category in vocab["categories"]:
        matching_tags = [
            tag for tag in category["tags"] if pack_set & set(tag["packs"])
        ]
        if matching_tags:
            result.append({**category, "tags": matching_tags})

    return result


def build_common_values_json(tags: list[dict[str, Any]]) -> str:
    """Convert tag list from JSON vocabulary format to DB common_values format.

    Input format:  [{"value": "rain", "aliases": ["rainy"], "packs": ["common"]}]
    Output format: '[{"value": "rain", "aliases": ["rainy"]}, ...]'

    Plain strings (no aliases) are stored as bare strings for compactness.
    """
    entries: list[str | dict[str, Any]] = []
    for tag in tags:
        if tag["aliases"]:
            entries.append({"value": tag["value"], "aliases": tag["aliases"]})
        else:
            entries.append(tag["value"])
    return json.dumps(entries)
