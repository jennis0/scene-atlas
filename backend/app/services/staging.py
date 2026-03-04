"""Staging directory helpers shared between the API and pipeline layers."""

import json
from pathlib import Path

FILE_MAP_NAME = ".file_map.json"


def load_file_map(staging_dir: Path) -> dict[str, str]:
    """Load the relative_path → staging_key mapping from the staging dir."""
    map_path = staging_dir / FILE_MAP_NAME
    if map_path.exists():
        with open(map_path) as f:
            return json.load(f)
    return {}


def save_file_map(staging_dir: Path, mapping: dict[str, str]) -> None:
    """Persist the relative_path → staging_key mapping."""
    map_path = staging_dir / FILE_MAP_NAME
    with open(map_path, "w") as f:
        json.dump(mapping, f)
