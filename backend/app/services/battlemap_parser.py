"""Battlemap filename/path parser with DB-driven tag categorization.

Extracts structured metadata from battlemap image paths:
- Author (from top-level folder or embedded "byAuthor" pattern)
- Variant group name (from folder hierarchy)
- Sub-variants (intermediate folders between group and file)
- Gridded status (boolean, from filename keywords)
- Grid dimensions (from NxN patterns in filename)
- Categorized tags (matched against DB-stored tag vocabulary)
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class BattlemapParser:
    """Parses battlemap image paths into structured metadata.

    Tag vocabulary is loaded from the TagCategory table in the database.
    Each category has common_values entries that can be plain strings
    or objects with aliases: {"value": "rain", "aliases": ["rainy", "raining"]}
    """

    def __init__(self, tag_categories: list[dict] | None = None):
        """Initialize parser.

        Args:
            tag_categories: List of dicts with 'name' and 'common_values' (JSON string).
                           If None, no tag categorization is performed (raw tags only).
        """
        # Regex patterns
        self._ordinal_re = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
        self._camel_re = re.compile(r"([a-z])([A-Z])|([a-zA-Z])([0-9])|([0-9])([a-zA-Z])")
        self._dim_re = re.compile(r"[\(\[ ]?(\d{1,3})\s*[xX]\s*(\d{1,3})[\)\] ]?")
        self._by_author_re = re.compile(r"[bB]y([A-Z][a-z]+|[A-Z]+|[a-z]+)")
        self._bracket_re = re.compile(r"[\(\[](.*?)[\)\]]")
        self._grid_negative_re = re.compile(r"\b(no[-_ ]?grid|gridless|ungridded|gl)\b")
        self._grid_positive_re = re.compile(r"\b(grid(ded)?|gd)\b")

        self._generic_folders = frozenset(
            {
                "singletons",
                "variants",
                "random",
                "miscellaneous",
                "assets",
                "tokens",
                "maps",
                "vtt",
                "roll20",
                "fvtt",
                "foundry",
                # Resolution / format folders
                "full resolution",
                "high resolution",
                "low resolution",
                "high res",
                "low res",
                "full res",
                "hi-res",
                "lo-res",
                "jpeg",
                "jpg",
                "png",
                "webp",
                "pdf",
                "tiff",
                "highres",
                "lowres",
                # Grid folders
                "gridded",
                "gridless",
                "no grid",
                "grid",
                "ungridded",
                # Other utility folders
                "originals",
                "source",
                "raw",
                "export",
                "output",
                "final",
                "preview",
                "thumbnails",
                "compressed",
            }
        )

        self._grid_stop_words = frozenset(
            {
                "gridded",
                "grid",
                "gridless",
                "nogrid",
                "no-grid",
                "ungridded",
            }
        )

        self._junk_words = frozenset(
            {
                # File/platform artifacts
                "jpg",
                "png",
                "webp",
                "vtt",
                "fvtt",
                "roll20",
                "foundry",
                "ppi",
                "dpi",
                "res",
                "high",
                "low",
                "mb",
                "copy",
                "final",
                "fin",
                "ver",
                "version",
                "optimized",
                "hd",
                "print",
                # Filler words
                "no",
                "the",
                "and",
                "of",
                "with",
                "by",
                "for",
                "in",
                "on",
                "to",
                "at",
                # Generic map words
                "map",
                "maps",
                "battlemap",
                "battlemaps",
                "tile",
                "tiles",
                "variation",
                "variant",
                "alternate",
                "alternative",
                "original",
                "base",
                "geomorph",
                "geomorphs",
            }
        )

        # Build tag vocabulary from DB categories
        self._vocabulary: dict[str, tuple[str, str]] = {}
        if tag_categories:
            self._build_vocabulary(tag_categories)

    def _build_vocabulary(self, tag_categories: list[dict]) -> None:
        """Build word→(category, value) lookup from TagCategory rows."""
        for cat in tag_categories:
            category_name = cat["name"]
            raw = cat.get("common_values")
            if not raw:
                continue

            try:
                values = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid common_values JSON for category '{category_name}'")
                continue

            for entry in values:
                if isinstance(entry, str):
                    # Simple string: word is both the lookup key and the canonical value
                    self._vocabulary[entry.lower()] = (category_name, entry.lower())
                elif isinstance(entry, dict):
                    # Object with aliases: {"value": "rain", "aliases": ["rainy", "raining"]}
                    canonical = entry.get("value", "").lower()
                    if canonical:
                        self._vocabulary[canonical] = (category_name, canonical)
                        for alias in entry.get("aliases", []):
                            self._vocabulary[alias.lower()] = (category_name, canonical)

    def _is_generic_folder(self, name: str) -> bool:
        """Check if a folder name is generic/utility (not a real group name).

        Normalizes the name (replace separators, lowercase) before checking
        against the generic set, so 'Full_Resolution' matches 'full resolution'.
        """
        normalized = name.lower().replace("_", " ").replace("-", " ").strip()
        return normalized in self._generic_folders

    def _split_camel(self, text: str) -> str:
        """Split CamelCase while protecting ordinals like 1st, 2nd, 3rd."""
        ordinals: list[str] = []

        def save_ordinal(m: re.Match) -> str:
            ordinals.append(m.group(0))
            return f" __ORD{len(ordinals) - 1}__ "

        text = self._ordinal_re.sub(save_ordinal, text)
        text = self._camel_re.sub(
            lambda m: (
                f"{m.group(1) or m.group(3) or m.group(5)} {m.group(2) or m.group(4) or m.group(6)}"
            ),
            text,
        )
        for i, ordinal in enumerate(ordinals):
            text = text.replace(f"__ORD{i}__", ordinal)
            text = text.replace(f"__ORD {i}__", ordinal)
        return text

    def _get_token_set(self, text: str) -> set[str]:
        """Normalize a string into a set of lowercase words."""
        text = text.replace("_", " ").replace("-", " ")
        expanded = self._split_camel(text)
        return set(re.findall(r"[a-zA-Z0-9]+", expanded.lower()))

    def _extract_raw_words(self, stem: str, exclusions: set[str]) -> list[str]:
        """Extract filtered words from a filename stem, protecting bracketed content."""
        protected_tokens: list[str] = []

        def protect(m: re.Match) -> str:
            content = m.group(1).replace("_", " ").strip()
            protected_tokens.append(content)
            return " __PROT__ "

        working = self._bracket_re.sub(protect, stem)
        working = working.replace("_", " ").replace("-", " ")
        working = self._split_camel(working)

        raw_words = re.findall(r"[a-zA-Z0-9]+", working)

        result: list[str] = []
        # Protected tokens (bracketed content) — add as multi-word phrases
        for token in protected_tokens:
            token_lower = token.lower()
            if token_lower not in exclusions and not any(
                w in exclusions for w in token_lower.split()
            ):
                result.append(token)

        # Individual words (min length 3 to skip fragments)
        for word in raw_words:
            w_low = word.lower()
            if (
                w_low not in exclusions
                and not w_low.isdigit()
                and len(w_low) >= 3
                and word != "__PROT__"
            ):
                result.append(word)

        return result

    def _categorize_words(self, words: list[str], confidence: float = 0.9) -> list[dict]:
        """Match words against the tag vocabulary, returning categorized tag dicts.

        Words not in the vocabulary are silently dropped.
        """
        seen: dict[tuple[str, str], dict] = {}

        for word in words:
            # For multi-word protected tokens, check each word
            sub_words = word.lower().split() if " " in word else [word.lower()]
            for w in sub_words:
                if w in self._vocabulary:
                    cat, val = self._vocabulary[w]
                    key = (cat, val)
                    if key not in seen or confidence > seen[key]["confidence"]:
                        seen[key] = {
                            "category": cat,
                            "value": val,
                            "confidence": confidence,
                            "source": "auto",
                        }

        return list(seen.values())

    def parse(self, relative_path: str) -> dict:
        """Parse a battlemap image path into structured metadata.

        Args:
            relative_path: Path relative to source dir, e.g.
                "czepeku/Island Fort/IslandFort_Night_Gridded.jpg"

        Returns:
            Dict with: author, variant_group_name, sub_variants, sub_variant,
                       tags, gridded, grid_width, grid_height, filename
        """
        clean = relative_path.strip()
        path_obj = Path(clean)
        parts = path_obj.parts
        stem = path_obj.stem

        # --- Author ---
        author = parts[0] if parts else "Unknown"
        author_match = self._by_author_re.search(stem)
        if author_match:
            author = author_match.group(1)

        # --- Grid detection (from filename) ---
        # Split CamelCase and replace separators so \b word boundaries work
        gridded = None
        grid_text = self._split_camel(stem).lower().replace("_", " ").replace("-", " ")
        if self._grid_negative_re.search(grid_text):
            gridded = False
        elif self._grid_positive_re.search(grid_text):
            gridded = True

        # Also check path parts for grid info
        if gridded is None:
            full_path_grid = self._split_camel(clean).lower().replace("_", " ").replace("-", " ")
            if self._grid_negative_re.search(full_path_grid):
                gridded = False
            elif self._grid_positive_re.search(full_path_grid):
                gridded = True

        # --- Dimensions ---
        grid_width = None
        grid_height = None
        dim_match = self._dim_re.search(stem)
        if dim_match:
            grid_width = int(dim_match.group(1))
            grid_height = int(dim_match.group(2))
            stem = stem.replace(dim_match.group(0), " ")

        # --- Hierarchy: author / [generic...] / group / [sub-variants...] / file ---
        sub_variants_raw: list[str] = []
        group_raw = "Unknown"
        group_from_folder = False
        if len(parts) >= 3:
            # Skip consecutive generic folders after the author to find the group
            group_idx = 1
            while group_idx < len(parts) - 1 and self._is_generic_folder(parts[group_idx]):
                group_idx += 1

            if group_idx < len(parts) - 1:
                # Found a non-generic folder — that's the group
                group_raw = parts[group_idx]
                sub_variants_raw = list(parts[group_idx + 1 : -1])
                group_from_folder = True
            else:
                # All intermediate folders are generic — the top folder IS the group
                # Clean it of dimensions/tier info
                top_clean = self._dim_re.sub("", parts[0]).strip()
                top_clean = re.sub(r"\b[Tt]ier\s*\d+\b", "", top_clean).strip()
                # Remove trailing generic words that leaked into the folder name
                for gw in ("full resolution", "gridless", "gridded", "high res", "low res"):
                    top_clean = re.sub(
                        rf"\b{re.escape(gw)}\b", "", top_clean, flags=re.IGNORECASE
                    ).strip()
                group_raw = top_clean or parts[0]
                sub_variants_raw = list(parts[1:-1])
                group_from_folder = True
                author = None  # Can't determine author from this structure

        # Fallback: infer group from filename stem
        if self._is_generic_folder(group_raw) or group_raw == "Unknown":
            group_raw = re.split(r"[\-\(\[\,]", stem)[0].strip()
            group_from_folder = False

        group_name = group_raw.replace("_", " ").strip()
        sub_variants = [s.replace("_", " ").strip() for s in sub_variants_raw]
        sub_variant = " / ".join(sub_variants) if sub_variants else None

        # --- Build exclusion set for tag extraction ---
        # Note: we intentionally do NOT exclude group name or sub-variant tokens —
        # those words are valid semantic tags (e.g. "desert" from "Desert Canyon").
        # Author exclusion only applies when group_from_folder=True (3+ level paths
        # where parts[0] is a real author folder, not a map group folder).
        # For 2-level paths (folder/file) parts[0] is the group/map folder.
        exclusions: set[str] = {"by"}
        exclusions.update(self._grid_stop_words)
        exclusions.update(self._junk_words)
        if author and group_from_folder:
            exclusions.update(self._get_token_set(author))
        if grid_width is not None:
            exclusions.update([str(grid_width), str(grid_height)])

        # --- Extract and categorize tags ---
        raw_words = self._extract_raw_words(stem, exclusions)
        tags = self._categorize_words(raw_words, confidence=0.9)

        # Also extract tags from path parts (lower confidence)
        path_words: list[str] = []
        for part in parts[:-1]:  # Skip filename
            part_tokens = self._get_token_set(part)
            for token in part_tokens:
                if token not in exclusions and len(token) >= 3:
                    path_words.append(token)
        path_tags = self._categorize_words(path_words, confidence=0.7)

        # Merge: filename tags win over path tags
        tag_keys = {(t["category"], t["value"]) for t in tags}
        for pt in path_tags:
            if (pt["category"], pt["value"]) not in tag_keys:
                tags.append(pt)

        return {
            "author": author,
            "variant_group_name": group_name.split("[(")[0].strip(),
            "group_from_folder": group_from_folder,
            "sub_variants": sub_variants,
            "sub_variant": sub_variant,
            "tags": tags,
            "gridded": gridded,
            "grid_width": grid_width,
            "grid_height": grid_height,
            "filename": path_obj.name,
        }

    def _common_prefix_words(self, a: str, b: str) -> str:
        """Find the common prefix of two strings, trimmed to a word boundary.

        Handles CamelCase, underscore, hyphen, and space separators.
        """
        # Normalize both to space-separated words
        a_norm = self._split_camel(a).replace("_", " ").replace("-", " ")
        b_norm = self._split_camel(b).replace("_", " ").replace("-", " ")

        a_words = a_norm.split()
        b_words = b_norm.split()

        common: list[str] = []
        for wa, wb in zip(a_words, b_words):
            if wa.lower() == wb.lower():
                common.append(wa)
            else:
                break

        return " ".join(common)

    def _merge_subvariant_folders(self, groups: list[dict]) -> list[dict]:
        """Merge folder-based groups that are sub-variants of the same variant group.

        Detects the pattern where the top-level folder IS the variant group and
        subfolders are sub-variants. E.g.:
            Abandoned Campsite 30x30/Abandoned Campsite/{files}
            Abandoned Campsite 30x30/Eerie/{files}
            Abandoned Campsite 30x30/Sunset/{files}

        Signal: multiple groups share the same "author" (top folder), and at least
        one group name is contained in the top folder name (after stripping dimensions).
        """
        # Bucket groups by their "author" (top-level folder)
        by_author: dict[str, list[dict]] = {}
        for g in groups:
            by_author.setdefault(g["author"], []).append(g)

        merged: list[dict] = []
        for author, author_groups in by_author.items():
            if len(author_groups) <= 1:
                merged.extend(author_groups)
                continue

            # Clean the top folder name: strip dimensions, normalize
            top_clean = self._dim_re.sub("", author).replace("_", " ").replace("-", " ").strip()
            top_tokens = set(top_clean.lower().split())

            # Check if any group name is contained in the top folder name
            match_found = False
            for g in author_groups:
                group_tokens = set(g["variant_group_name"].lower().split())
                # Group name tokens are a subset of top folder tokens
                if group_tokens and group_tokens.issubset(top_tokens):
                    match_found = True
                    break

            if match_found:
                # Top folder is the variant group — merge all into one
                all_files: list[dict] = []
                for g in author_groups:
                    # Update sub_variant in parsed data to include the subfolder
                    for f in g["files"]:
                        subfolder = g["variant_group_name"]
                        existing_sub = f["parsed"].get("sub_variant")
                        if existing_sub:
                            f["parsed"]["sub_variant"] = f"{subfolder} / {existing_sub}"
                        else:
                            f["parsed"]["sub_variant"] = subfolder
                    all_files.extend(g["files"])

                merged.append(
                    {
                        "author": None,  # Can't determine author from this structure
                        "variant_group_name": top_clean,
                        "files": all_files,
                    }
                )
            else:
                merged.extend(author_groups)

        return merged

    def group_files(self, relative_paths: list[str]) -> list[dict]:
        """Group a list of relative paths into variant groups.

        Pass 1: Run parse() on each file. If group_from_folder=True, group by
                 (author, variant_group_name).
        Pass 2: For files where group_from_folder=False, group by filename prefix
                 within the same parent folder.

        Returns:
            List of dicts: {
                "author": str | None,
                "variant_group_name": str,
                "files": [{"relative_path": str, "parsed": dict}]
            }
        """
        # Parse all files
        parsed_files = []
        for rp in relative_paths:
            parsed = self.parse(rp)
            parsed_files.append({"relative_path": rp, "parsed": parsed})

        # Split into folder-based and filename-based groups
        folder_based: dict[tuple[str, str], list[dict]] = {}
        filename_based: list[dict] = []

        for pf in parsed_files:
            if pf["parsed"]["group_from_folder"]:
                key = (pf["parsed"]["author"], pf["parsed"]["variant_group_name"])
                folder_based.setdefault(key, []).append(pf)
            else:
                filename_based.append(pf)

        result: list[dict] = []

        # Pass 1: folder-based groups
        raw_folder_groups: list[dict] = []
        for (author, group_name), files in folder_based.items():
            raw_folder_groups.append(
                {
                    "author": author,
                    "variant_group_name": group_name,
                    "files": files,
                }
            )

        # Pass 1.5: merge folder-based groups that are actually sub-variants
        # of the same variant group. Detects the pattern:
        #   GroupName 30x30/SubVariantA/{files}
        #   GroupName 30x30/SubVariantB/{files}
        # where the top folder IS the variant group and subfolders are sub-variants.
        raw_folder_groups = self._merge_subvariant_folders(raw_folder_groups)
        result.extend(raw_folder_groups)

        # Pass 2: prefix-based merging within same parent folder
        if filename_based:
            # Group by parent folder first
            by_folder: dict[str, list[dict]] = {}
            for pf in filename_based:
                parent = str(Path(pf["relative_path"]).parent)
                by_folder.setdefault(parent, []).append(pf)

            for parent_folder, files in by_folder.items():
                # Sort by filename stem for prefix detection
                files.sort(key=lambda f: Path(f["relative_path"]).stem.lower())

                # Infer author from top-level folder
                top_folder = (
                    Path(files[0]["relative_path"]).parts[0]
                    if len(Path(files[0]["relative_path"]).parts) > 1
                    else None
                )

                groups: list[dict] = []
                current_group: dict | None = None
                current_prefix: str = ""

                for f in files:
                    stem = Path(f["relative_path"]).stem

                    if current_group is None:
                        # Start first group
                        current_prefix = self._split_camel(stem).replace("_", " ").replace("-", " ")
                        current_group = {
                            "author": top_folder,
                            "variant_group_name": f["parsed"]["variant_group_name"],
                            "files": [f],
                        }
                    else:
                        # Check common prefix with current group
                        common = self._common_prefix_words(current_prefix, stem)

                        if len(common) >= 6:
                            # Merge into current group — tighten prefix
                            current_prefix = common
                            current_group["files"].append(f)
                        else:
                            # Start new group
                            groups.append(current_group)
                            current_prefix = (
                                self._split_camel(stem).replace("_", " ").replace("-", " ")
                            )
                            current_group = {
                                "author": top_folder,
                                "variant_group_name": f["parsed"]["variant_group_name"],
                                "files": [f],
                            }

                if current_group:
                    # For multi-file prefix groups, use the common prefix as group name
                    if len(current_group["files"]) > 1 and current_prefix:
                        current_group["variant_group_name"] = current_prefix.strip()
                    groups.append(current_group)

                result.extend(groups)

        return result


if __name__ == "__main__":
    parser = BattlemapParser()
