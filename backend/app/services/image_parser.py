"""Image filename/path parser with DB-driven tag categorization.

Extracts structured metadata from image paths:
- Author (from top-level folder or embedded "byAuthor" pattern)
- Group name (from folder hierarchy)
- Subgroups (intermediate folders between group and file)
- Gridded status (boolean, from filename keywords — battlemaps only)
- Grid dimensions (from NxN patterns in filename — battlemaps only)
- Categorized tags (matched against DB-stored tag vocabulary)
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


_CAMEL_RE = re.compile(r"([a-z])([A-Z])|([a-zA-Z])([0-9])|([0-9])([a-zA-Z])")


def _split_camel_static(text: str) -> str:
    """Split CamelCase boundaries into spaces (module-level helper)."""
    return _CAMEL_RE.sub(
        lambda m: (
            f"{m.group(1) or m.group(3) or m.group(5)} {m.group(2) or m.group(4) or m.group(6)}"
        ),
        text,
    )


def build_search_text(
    name: str | None,
    filename: str | None,
    author: str | None = None,
    tags: list[dict] | None = None,
    subgroup: str | None = None,
) -> str:
    """Build a pre-tokenized search string for FTS5 indexing.

    CamelCase-splits name and filename so that "desertCanyon" becomes
    "desert Canyon", letting FTS5's unicode61 tokenizer index each word
    separately.  Also appends tag values and subgroup text.
    """
    parts: list[str] = []

    for raw in (name, filename, subgroup):
        if not raw:
            continue
        # Strip file extension from filename
        cleaned = re.sub(r"\.[^.]+$", "", raw)
        # Replace separators with spaces, then split CamelCase
        cleaned = cleaned.replace("_", " ").replace("-", " ").replace("$", " ")
        cleaned = _split_camel_static(cleaned)
        parts.append(cleaned)

    if author:
        parts.append(_split_camel_static(author))

    if tags:
        for t in tags:
            val = t.get("value", "")
            if val:
                parts.append(val)

    return " ".join(parts)


class ImageParser:
    """Parses image paths into structured metadata.

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
        self._dim_re = re.compile(r"(?<!\d)[\(\[ ]?(\d{1,3})\s*[xX]\s*(\d{1,3})[\)\] ]?(?!\d)")
        self._by_author_re = re.compile(r"[bB]y([A-Z][a-z]+|[A-Z]+|[a-z]+)")
        self._bracket_re = re.compile(r"[\(\[](.*?)[\)\]]")
        self._grid_negative_re = re.compile(r"\b(no[-_ ]?grid|gridless|ungridded|gl)\b")
        self._grid_hex_re = re.compile(r"\b(hexgrid|hex[-_ ]?grid|hg)\b")
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
                "hd",
                "fr",
                # Grid folders
                "gridded",
                "gridless",
                "no grid",
                "grid",
                "ungridded",
                "hexgrid",
                "hex grid",
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
                "hexgrid",
                "hex-grid",
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

        # Scene-specific junk words: remove map/tile terms that could be
        # meaningful in scene filenames (e.g. "World Map of Faerun")
        self._scene_junk_words = self._junk_words - {
            "map",
            "maps",
            "tile",
            "tiles",
            "geomorph",
            "geomorphs",
        }

        # --- Name-cleaning patterns ---
        self._dpi_re = re.compile(r"\b\d+\s*(dpi|ppi)\b", re.IGNORECASE)
        self._pixel_dim_re = re.compile(r"\b\d{4,}\s*[xX]\s*\d{4,}\b")
        self._tier_re = re.compile(r"\bTier\s*\d+\b", re.IGNORECASE)
        self._vol_re = re.compile(r"\bVol(ume)?\s*\d*\b", re.IGNORECASE)
        self._pricing_re = re.compile(r"\$\d*\s*Rewards?\b", re.IGNORECASE)
        self._full_res_re = re.compile(r"\bFull\s+Resolution\s*(Files?)?\b", re.IGNORECASE)
        self._fr_files_re = re.compile(r"\bFR\s+Files?\b", re.IGNORECASE)
        self._platform_re = re.compile(r"\b(FVTT|Roll\s*20|R20|VTT)\b", re.IGNORECASE)
        self._maps_word_re = re.compile(r"\bMaps\b", re.IGNORECASE)
        self._grid_name_re = re.compile(
            r"\b(No\s*Grid|Grid(ded|less)?|Ungridded|GL|GD|Hexgrid|Hex[-_ ]?Grid|HG)\b",
            re.IGNORECASE,
        )
        self._abbrev_rejoin_re = re.compile(r"\b([A-Z]{1,2})\s+(\d+)\b")
        self._tight_alpha_dash_re = re.compile(r"(?<=[a-zA-Z])-(?=[a-zA-Z])")
        self._multi_space_re = re.compile(r"\s+")

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
        """Split CamelCase while protecting ordinals like 1st, 2nd, 3rd.

        Runs two passes so adjacent transitions are caught (e.g. "Night3Grid"
        → "Night 3Grid" on pass 1, "Night 3 Grid" on pass 2).  Ordinals are
        re-protected between passes so "1st" doesn't get split.
        """

        def _one_pass(t: str) -> str:
            ordinals: list[str] = []

            def save_ordinal(m: re.Match) -> str:
                ordinals.append(m.group(0))
                return f" __ORD{len(ordinals) - 1}__ "

            t = self._ordinal_re.sub(save_ordinal, t)
            t = self._camel_re.sub(
                lambda m: (
                    f"{m.group(1) or m.group(3) or m.group(5)} "
                    f"{m.group(2) or m.group(4) or m.group(6)}"
                ),
                t,
            )
            for i, ordinal in enumerate(ordinals):
                t = t.replace(f"__ORD{i}__", ordinal)
                t = t.replace(f"__ORD {i}__", ordinal)
            return t

        text = _one_pass(text)
        text = _one_pass(text)
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

    # -------------------------------------------------------------------
    # Name-cleaning helpers
    # -------------------------------------------------------------------

    def _normalize_text(self, text: str) -> str:
        """Shared formatting: separators → spaces, CamelCase split, rejoin abbreviations."""
        name = text.replace("_", " ")
        # Slug-style dashes (alpha-alpha): replace with space
        name = self._tight_alpha_dash_re.sub(" ", name)
        # Alpha-digit dashes: replace with " - " to separate but keep dash
        name = re.sub(r"(?<=[a-zA-Z])-(?=\d)", " - ", name)
        name = re.sub(r"(?<=\d)-(?=[a-zA-Z])", " - ", name)
        name = self._split_camel(name)
        name = self._abbrev_rejoin_re.sub(r"\1\2", name)
        return name

    def _remove_noise(self, text: str, *, keep_grid: bool = False) -> str:
        """Remove resolution, tier, pricing, platform markers from a normalised string."""
        name = self._dpi_re.sub("", text)
        name = self._pixel_dim_re.sub("", name)
        name = self._dim_re.sub("", name)
        name = self._tier_re.sub("", name)
        name = self._vol_re.sub("", name)
        name = self._pricing_re.sub("", name)
        name = name.replace("$", "")
        name = self._full_res_re.sub("", name)
        name = self._fr_files_re.sub("", name)
        name = self._platform_re.sub("", name)
        name = self._maps_word_re.sub("", name)
        if not keep_grid:
            name = self._grid_name_re.sub("", name)
        return name

    def _deduplicate_sequences(self, words: list[str]) -> list[str]:
        """Remove repeated multi-word sequences (later occurrence removed)
        AND consecutive identical single words."""
        result = self._dedup_multi_word(words)
        return self._dedup_consecutive(result)

    def _dedup_multi_word(self, words: list[str]) -> list[str]:
        """Remove repeated multi-word sequences (length >= 2, longest first)."""
        result = list(words)
        for length in range(len(result) // 2, 1, -1):
            i = 0
            while i <= len(result) - 2 * length:
                seq = [w.lower() for w in result[i : i + length]]
                removed = False
                for j in range(i + length, len(result) - length + 1):
                    candidate = [w.lower() for w in result[j : j + length]]
                    if seq == candidate:
                        result = result[:j] + result[j + length :]
                        removed = True
                        break
                if not removed:
                    i += 1
        return result

    @staticmethod
    def _dedup_consecutive(words: list[str]) -> list[str]:
        """Remove adjacent identical words (e.g. 'Blacksmith Blacksmith' → 'Blacksmith')."""
        result: list[str] = []
        for w in words:
            if not result or w.lower() != result[-1].lower():
                result.append(w)
        return result

    def _strip_author_prefix(self, words: list[str], author: str | None) -> list[str]:
        """Remove leading words that concatenate to the author name."""
        if not author or not words:
            return words
        author_norm = re.sub(
            r"[^a-z0-9]",
            "",
            self._split_camel(author.replace("_", " ").replace("-", " ")).lower(),
        )
        for n in range(1, min(len(words) + 1, 5)):
            prefix = re.sub(r"[^a-z0-9]", "", "".join(words[:n]).lower())
            if prefix == author_norm:
                return words[n:]
        return words

    def _strip_word_prefix(self, words: list[str], prefix_words: list[str]) -> list[str]:
        """Remove leading words that match *prefix_words* (case-insensitive)."""
        if not prefix_words or len(words) < len(prefix_words):
            return words
        if all(w.lower() == p.lower() for w, p in zip(words, prefix_words, strict=False)):
            return words[len(prefix_words) :]
        return words

    def _strip_word_sequence(self, words: list[str], seq_words: list[str]) -> list[str]:
        """Remove first occurrence of a contiguous word sequence (anywhere)."""
        if not seq_words:
            return words
        seq_lower = [w.lower() for w in seq_words]
        seq_len = len(seq_lower)
        for i in range(len(words) - seq_len + 1):
            if [w.lower() for w in words[i : i + seq_len]] == seq_lower:
                return words[:i] + words[i + seq_len :]
        return words

    @staticmethod
    def _title_case_preserve(text: str) -> str:
        """Title-case words that are entirely lowercase, leave others untouched.

        'dread hills saloon' → 'Dread Hills Saloon'
        'DUNGEONS - DRAGONGATE' → 'DUNGEONS - DRAGONGATE'
        'Rocky Coast' → 'Rocky Coast'   (already mixed-case)
        """
        parts: list[str] = []
        for word in text.split():
            if word == word.lower() and word.isalpha():
                parts.append(word.capitalize())
            else:
                parts.append(word)
        return " ".join(parts)

    def _finalize_name(self, words: list[str], fallback: str) -> str:
        """Join words, normalize dashes/spaces, guard against empty result."""
        name = " ".join(words)
        # Normalize: each dash gets " - " around it, collapse spaces, then
        # collapse consecutive dashes ("- - " → "- ")
        name = re.sub(r"\s*-\s*", " - ", name)
        name = self._multi_space_re.sub(" ", name).strip()
        name = re.sub(r"(- ){2,}", "- ", name)
        name = name.strip(" -")
        if not name:
            name = self._normalize_text(fallback)
            name = self._multi_space_re.sub(" ", name).strip()
        return name

    def _clean_group_name(self, raw: str, author: str | None = None) -> str:
        """Clean a raw folder/filename-derived name into a group name.

        Strips noise (Tier, DPI, dimensions, pricing, platform markers, grid
        state) and normalises formatting (CamelCase → spaces, slug-dashes → spaces).
        """
        name = self._normalize_text(raw)
        name = self._remove_noise(name)
        # Strip leading numbering like "07. " or "10. "
        name = re.sub(r"^\d+\.\s*", "", name)
        words = name.split()
        words = self._strip_author_prefix(words, author)
        words = self._deduplicate_sequences(words)
        result = self._finalize_name(words, raw)
        # Title-case words that are all-lowercase (slug-style input)
        if result == result.lower():
            result = self._title_case_preserve(result)
        return result

    def _build_name(
        self,
        stem: str,
        author: str | None,
        group_name: str,
        subgroups: list[str] | None = None,
    ) -> str:
        """Build a display name for an individual scene from the filename stem.

        Removes all noise (grid state, DPI, pricing, platform markers, etc.),
        author prefix, duplicate sequences, the group name, and
        subgroup folder names.
        """
        name = self._normalize_text(stem)
        # Strip author BEFORE noise removal so compound names like
        # "DreadMaps" → "Dread Maps" still match the author "Dreadmaps"
        words = name.split()
        words = self._strip_author_prefix(words, author)
        name = " ".join(words)
        name = self._remove_noise(name)

        words = name.split()
        # Multi-word dedup first (e.g. "Snowy Forest...Snowy Forest")
        words = self._dedup_multi_word(words)
        # Strip group name (sequence match — finds it anywhere, not just prefix,
        # so it works even when noise like "G_" precedes the group name)
        gn_words = [w for w in group_name.split() if w != "-"] if group_name else []
        candidate = self._strip_word_sequence(words, gn_words)
        if candidate:  # guard: don't strip if it empties the list
            words = candidate
        # Strip subgroup folder names (already captured in subgroup field)
        if subgroups:
            for sg in subgroups:
                sg_cleaned = self._normalize_text(sg)
                sg_cleaned = self._remove_noise(sg_cleaned)
                # Strip leading numbering (e.g. "02 Apple Press" → "Apple Press")
                sg_cleaned = re.sub(r"^\d+\.?\s*", "", sg_cleaned).strip()
                sg_words = [w for w in sg_cleaned.split() if w != "-"]
                if not sg_words:
                    continue
                stripped = self._strip_word_sequence(words, sg_words)
                if stripped:  # guard: don't strip if it empties the list
                    words = stripped
        words = self._dedup_consecutive(words)

        result = self._finalize_name(words, name)
        if result == result.lower():
            result = self._title_case_preserve(result)
        return result

    def parse(self, relative_path: str, image_type: str = "battlemap") -> dict:
        """Parse an image path into structured metadata.

        Args:
            relative_path: Path relative to source dir, e.g.
                "czepeku/Island Fort/IslandFort_Night_Gridded.jpg"
            image_type: "battlemap" or "scene". Scenes skip grid detection
                and use a reduced junk word list.

        Returns:
            Dict with: author, group_name, subgroups, subgroup,
                       tags, gridded, grid_width, grid_height, filename, name
        """
        is_scene = image_type == "scene"
        clean = relative_path.strip()
        path_obj = Path(clean)
        parts = path_obj.parts
        stem = path_obj.stem

        # --- Author ---
        author = parts[0] if parts else "Unknown"
        author_match = self._by_author_re.search(stem)
        if author_match:
            author = author_match.group(1)

        # --- Grid detection (from filename) — battlemaps only ---
        gridded = None
        grid_type = None
        grid_width = None
        grid_height = None

        if not is_scene:
            grid_text = self._split_camel(stem).lower().replace("_", " ").replace("-", " ")
            if self._grid_negative_re.search(grid_text):
                gridded = False
            elif self._grid_hex_re.search(grid_text):
                gridded = True
                grid_type = "hex"
            elif self._grid_positive_re.search(grid_text):
                gridded = True
                grid_type = "square"

            # Also check path parts for grid info
            if gridded is None:
                full_path_grid = (
                    self._split_camel(clean).lower().replace("_", " ").replace("-", " ")
                )
                if self._grid_negative_re.search(full_path_grid):
                    gridded = False
                elif self._grid_hex_re.search(full_path_grid):
                    gridded = True
                    grid_type = "hex"
                elif self._grid_positive_re.search(full_path_grid):
                    gridded = True
                    grid_type = "square"

            # --- Dimensions ---
            dim_match = self._dim_re.search(stem)
            if dim_match:
                grid_width = int(dim_match.group(1))
                grid_height = int(dim_match.group(2))
                stem = stem.replace(dim_match.group(0), " ")
        else:
            # Still strip dimension patterns from stem for cleaner names,
            # but don't record them as grid dimensions
            dim_match = self._dim_re.search(stem)
            if dim_match:
                stem = stem.replace(dim_match.group(0), " ")

        # --- Hierarchy: author / [generic...] / group / [subgroups...] / file ---
        subgroups_raw: list[str] = []
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
                subgroups_raw = list(parts[group_idx + 1 : -1])
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
                subgroups_raw = list(parts[1:-1])
                group_from_folder = True
                author = None  # Can't determine author from this structure

        # Fallback: infer group from filename stem
        if self._is_generic_folder(group_raw) or group_raw == "Unknown":
            # Take first underscore segment (or first dash segment, or whole stem)
            if "_" in stem:
                group_raw = stem.split("_")[0]
            elif "-" in stem:
                group_raw = stem.split("-")[0]
            else:
                group_raw = stem
            group_from_folder = False

        # --- Clean group name & build scene name ---
        effective_author = author if group_from_folder else None
        group_name = self._clean_group_name(group_raw, author=effective_author)

        subgroups = [s.replace("_", " ").strip() for s in subgroups_raw]
        subgroup = " / ".join(subgroups) if subgroups else None

        name = self._build_name(stem, author, group_name, subgroups)

        # --- Build exclusion set for tag extraction ---
        # Note: we intentionally do NOT exclude group name or subgroup tokens —
        # those words are valid semantic tags (e.g. "desert" from "Desert Canyon").
        # Author exclusion only applies when group_from_folder=True (3+ level paths
        # where parts[0] is a real author folder, not a map group folder).
        # For 2-level paths (folder/file) parts[0] is the group/map folder.
        exclusions: set[str] = {"by"}
        if not is_scene:
            exclusions.update(self._grid_stop_words)
        exclusions.update(self._scene_junk_words if is_scene else self._junk_words)
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
            "group_name": group_name,
            "name": name,
            "group_from_folder": group_from_folder,
            "subgroups": subgroups,
            "subgroup": subgroup,
            "tags": tags,
            "gridded": gridded,
            "grid_type": grid_type,
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
        for wa, wb in zip(a_words, b_words, strict=False):
            if wa.lower() == wb.lower():
                common.append(wa)
            else:
                break

        return " ".join(common)

    def _merge_subgroup_folders(self, groups: list[dict]) -> list[dict]:
        """Merge folder-based groups that are subgroups of the same group.

        Detects the pattern where the top-level folder IS the group and
        subfolders are subgroups. E.g.:
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
                group_tokens = set(g["group_name"].lower().split())
                # Group name tokens are a subset of top folder tokens
                if group_tokens and group_tokens.issubset(top_tokens):
                    match_found = True
                    break

            if match_found:
                # Top folder is the group — merge all into one
                all_files: list[dict] = []
                for g in author_groups:
                    # Update subgroup in parsed data to include the subfolder
                    for f in g["files"]:
                        subfolder = g["group_name"]
                        existing_sub = f["parsed"].get("subgroup")
                        if existing_sub:
                            f["parsed"]["subgroup"] = f"{subfolder} / {existing_sub}"
                        else:
                            f["parsed"]["subgroup"] = subfolder
                    all_files.extend(g["files"])

                merged.append(
                    {
                        "author": None,  # Can't determine author from this structure
                        "group_name": top_clean,
                        "files": all_files,
                    }
                )
            else:
                merged.extend(author_groups)

        return merged

    def group_files(self, relative_paths: list[str], image_type: str = "battlemap") -> list[dict]:
        """Group a list of relative paths into groups.

        Pass 1: Run parse() on each file. If group_from_folder=True, group by
                 (author, group_name).
        Pass 2: For files where group_from_folder=False, group by filename prefix
                 within the same parent folder.

        Args:
            relative_paths: List of relative file paths.
            image_type: "battlemap" or "scene" — passed to parse().

        Returns:
            List of dicts: {
                "author": str | None,
                "group_name": str,
                "files": [{"relative_path": str, "parsed": dict}]
            }
        """
        # Parse all files
        parsed_files = []
        for rp in relative_paths:
            parsed = self.parse(rp, image_type=image_type)
            parsed_files.append({"relative_path": rp, "parsed": parsed})

        # Split into folder-based and filename-based groups
        folder_based: dict[tuple[str, str], list[dict]] = {}
        filename_based: list[dict] = []

        for pf in parsed_files:
            if pf["parsed"]["group_from_folder"]:
                key = (pf["parsed"]["author"], pf["parsed"]["group_name"])
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
                    "group_name": group_name,
                    "files": files,
                }
            )

        # Pass 1.5: merge folder-based groups that are actually subgroups
        # of the same group. Detects the pattern:
        #   GroupName 30x30/SubGroupA/{files}
        #   GroupName 30x30/SubGroupB/{files}
        # where the top folder IS the group and subfolders are subgroups.
        raw_folder_groups = self._merge_subgroup_folders(raw_folder_groups)
        result.extend(raw_folder_groups)

        # Pass 2: prefix-based merging within same parent folder
        if filename_based:
            # Group by parent folder first
            by_folder: dict[str, list[dict]] = {}
            for pf in filename_based:
                parent = str(Path(pf["relative_path"]).parent)
                by_folder.setdefault(parent, []).append(pf)

            for _parent_folder, files in by_folder.items():
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
                            "group_name": f["parsed"]["group_name"],
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
                                "group_name": f["parsed"]["group_name"],
                                "files": [f],
                            }

                if current_group:
                    # For multi-file prefix groups, use the common prefix as group name
                    if len(current_group["files"]) > 1 and current_prefix:
                        current_group["group_name"] = current_prefix.strip()
                    groups.append(current_group)

                result.extend(groups)

        return result


if __name__ == "__main__":
    parser = ImageParser()
