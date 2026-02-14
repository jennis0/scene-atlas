"""Metadata extraction tasks for Prefect flows."""

import logging
import re
from pathlib import Path
from typing import List

from prefect import task

logger = logging.getLogger(__name__)


# Tag extraction patterns
TAG_PATTERNS = {
    "grid": {
        "gridded": [r"(?i)\bgrid(ded)?\b", r"(?i)_grid\b", r"(?i)-grid\b", r"^GR[_-]", r"^Gridded"],
        "no-grid": [r"(?i)\bno[-_]?grid\b", r"(?i)\bgridless\b", r"^GL[_-]", r"^Gridless"],
        "hex-grid": [r"(?i)\bhex[-_]?grid\b"],
    },
    "season": {
        "winter": [r"(?i)\bwinter\b"],
        "summer": [r"(?i)\bsummer\b"],
        "autumn": [r"(?i)\b(fall|autumn)\b"],
        "spring": [r"(?i)\bspring\b"],
    },
    "lighting": {
        "night": [r"(?i)\bnight\b"],
        "day": [r"(?i)\bday\b", r"(?i)\bdaytime\b"],
        "dusk": [r"(?i)\bdusk\b"],
        "dawn": [r"(?i)\bdawn\b"],
        "twilight": [r"(?i)\btwilight\b"],
    },
    "state": {
        "bloody": [r"(?i)\bblood(y|ed)?\b"],
        "ruined": [r"(?i)\bruin(ed|s)?\b"],
        "burned": [r"(?i)\b(burn(ed|t)?|fire)\b"],
        "abandoned": [r"(?i)\babandoned\b"],
        "overgrown": [r"(?i)\bovergrown\b"],
        "polluted": [r"(?i)\bpolluted\b"],
    },
    "theme": {
        "fey": [r"(?i)\bfey(wild)?\b"],
        "shadow": [r"(?i)\bshadow(fell)?\b"],
        "fire": [r"(?i)\bfire\b", r"(?i)\bflame\b"],
        "ice": [r"(?i)\bice\b", r"(?i)\bfrozen\b"],
        "underdark": [r"(?i)\bunderdark\b"],
    },
    "weather": {
        "rain": [r"(?i)\brain(y|ing)?\b"],
        "snow": [r"(?i)\bsnow(y|ing)?\b"],
        "fog": [r"(?i)\bfog(gy)?\b"],
        "storm": [r"(?i)\bstorm(y)?\b"],
        "mist": [r"(?i)\bmist(y)?\b"],
    },
    "population": {
        "empty": [r"(?i)\bempty\b"],
        "furnished": [r"(?i)\bfurnished\b"],
        "populated": [r"(?i)\bpopulated\b"],
        "battle": [r"(?i)\bbattle\b"],
    }
}


@task(name="extract_tags_from_filename", retries=1)
def extract_tags_from_filename(filename: str) -> List[dict]:
    """Extract tags from filename using pattern matching.

    Args:
        filename: Image filename (without path)

    Returns:
        List of tag dicts: [{"category": "grid", "value": "gridded", "confidence": 0.9, "source": "auto"}, ...]
    """
    tags = []

    for category, patterns_dict in TAG_PATTERNS.items():
        for value, regex_list in patterns_dict.items():
            for regex in regex_list:
                if re.search(regex, filename):
                    tags.append({
                        "category": category,
                        "value": value,
                        "confidence": 0.9,  # High confidence for direct filename matches
                        "source": "auto",
                    })
                    break  # Only add each tag once per category

    logger.debug(f"Extracted {len(tags)} tags from filename: {filename}")
    return tags


@task(name="extract_tags_from_path", retries=1)
def extract_tags_from_path(filepath: Path) -> List[dict]:
    """Extract tags from file path (parent directories).

    Args:
        filepath: Full path to the image

    Returns:
        List of tag dicts with lower confidence scores
    """
    tags = []
    path_parts = filepath.parts

    # Check each part of the path
    for part in path_parts:
        for category, patterns_dict in TAG_PATTERNS.items():
            for value, regex_list in patterns_dict.items():
                for regex in regex_list:
                    if re.search(regex, part):
                        tags.append({
                            "category": category,
                            "value": value,
                            "confidence": 0.7,  # Lower confidence for path-based tags
                            "source": "auto",
                        })
                        break

    logger.debug(f"Extracted {len(tags)} tags from path: {filepath}")
    return tags


@task(name="infer_author", retries=1)
def infer_author(filepath: Path) -> str | None:
    """Infer author/creator from file path.

    Assumes structure like: source_dir/{author}/{mapgroup}/...

    Args:
        filepath: Full path to the image

    Returns:
        Author name or None
    """
    path_parts = filepath.parts

    # Find the "images" folder index
    try:
        images_index = path_parts.index("images")
        # Author should be right after "images" folder
        if images_index + 1 < len(path_parts):
            author = path_parts[images_index + 1]
            # Skip if it looks like a file
            if not author.endswith(('.jpg', '.png', '.jpeg', '.webp')):
                logger.debug(f"Inferred author '{author}' from path")
                return author
    except ValueError:
        pass

    # Fallback: look for a parent directory that might be the author
    skip_folders = {"images", "maps", "battlemaps", "assets", "resources", "data"}

    for i, part in enumerate(path_parts[:-2]):  # Skip filename and immediate parent
        if part.lower() not in skip_folders and len(part) > 2:
            return part

    return None


@task(name="infer_base_name", retries=1)
def infer_base_name(filename: str, tags: List[dict]) -> str:
    """Infer the base map name by removing variant suffixes.

    Args:
        filename: Image filename
        tags: Extracted tags (to remove tag values from name)

    Returns:
        Base name without variant suffixes
    """
    # Remove file extension
    name = Path(filename).stem

    # Remove common prefixes (GL/GR for Gridless/Gridded)
    name = re.sub(r"^(GL|GR)[_-]", "", name)

    # For underscore/hyphen separated names, use the first substantial part
    if "_" in name or "-" in name:
        parts = re.split(r"[_-]", name)
        # Use first part that's longer than 2 characters
        for part in parts:
            if len(part) > 2:
                name = part
                break

    # Add space before capitals for readability (CamelCase -> Camel Case)
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)

    # Clean up multiple spaces
    name = re.sub(r"\s+", " ", name).strip()

    logger.debug(f"Inferred base name '{name}' from filename '{filename}'")
    return name if len(name) >= 3 else Path(filename).stem


@task(name="merge_tags", retries=1)
def merge_tags(tags_list: List[List[dict]]) -> List[dict]:
    """Merge multiple tag lists, keeping only unique tags with highest confidence.

    Args:
        tags_list: List of tag lists to merge

    Returns:
        Merged list of unique tags
    """
    tag_map = {}  # (category, value) -> tag dict

    for tags in tags_list:
        for tag in tags:
            key = (tag["category"], tag["value"])
            if key not in tag_map or tag["confidence"] > tag_map[key]["confidence"]:
                tag_map[key] = tag

    merged = list(tag_map.values())
    logger.debug(f"Merged {sum(len(t) for t in tags_list)} tags into {len(merged)} unique tags")
    return merged


# --- Non-Prefect functions for upload metadata preview ---

def _extract_tags_from_filename_raw(filename: str) -> list[dict]:
    """Extract tags from filename without Prefect task wrapper.

    Same logic as extract_tags_from_filename but callable outside Prefect flows.
    """
    tags = []
    for category, patterns_dict in TAG_PATTERNS.items():
        for value, regex_list in patterns_dict.items():
            for regex in regex_list:
                if re.search(regex, filename):
                    tags.append({
                        "category": category,
                        "value": value,
                        "confidence": 0.9,
                        "source": "auto",
                    })
                    break
    return tags


def _infer_base_name_raw(filename: str) -> str:
    """Infer base name without Prefect task wrapper."""
    name = Path(filename).stem
    name = re.sub(r"^(GL|GR)[_-]", "", name)
    if "_" in name or "-" in name:
        parts = re.split(r"[_-]", name)
        for part in parts:
            if len(part) > 2:
                name = part
                break
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    name = re.sub(r"\s+", " ", name).strip()
    return name if len(name) >= 3 else Path(filename).stem


def extract_metadata_from_upload(
    filenames: list[str],
    relative_paths: list[str] | None = None,
) -> dict:
    """Extract metadata from uploaded file names and directory structure.

    This is a pure function (no side effects, not a Prefect task) called at upload
    time to present metadata preview to the user before ingestion.

    Detects directory structure patterns:
    - {author}/{variant_group}/{variant} (depth 3+)
    - {variant_group}/{variant} (depth 2)
    - {variant} (flat, depth 1)

    Args:
        filenames: List of original filenames
        relative_paths: Optional list of relative paths (from webkitRelativePath or ZIP).
                       Each path includes the filename, e.g., "author/group/image.jpg"

    Returns:
        {
            "detected_author": str | None,
            "detected_variant_group": str | None,
            "files": [{"filename": str, "tags": [...]}]
        }
    """
    detected_author = None
    detected_variant_group = None

    # Analyze directory structure from relative paths
    if relative_paths:
        path_parts_list = []
        for rp in relative_paths:
            parts = Path(rp).parts
            if len(parts) > 1:  # Has directory structure
                path_parts_list.append(parts)

        if path_parts_list:
            max_depth = max(len(p) for p in path_parts_list)

            if max_depth >= 3:
                # Pattern: {author}/{variant_group}/{variant}
                detected_author = path_parts_list[0][0]
                detected_variant_group = path_parts_list[0][1]
            elif max_depth >= 2:
                # Pattern: {variant_group}/{variant}
                detected_variant_group = path_parts_list[0][0]

    # If no variant group detected from structure, try to infer from filenames
    if not detected_variant_group and filenames:
        detected_variant_group = _infer_base_name_raw(filenames[0])

    # Extract tags from each filename
    files_info = []
    for filename in filenames:
        tags = _extract_tags_from_filename_raw(filename)
        files_info.append({
            "filename": filename,
            "tags": tags,
        })

    return {
        "detected_author": detected_author,
        "detected_variant_group": detected_variant_group,
        "files": files_info,
    }
