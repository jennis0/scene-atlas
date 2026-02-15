# BattlemapParser — Metadata Extraction

## Overview

`BattlemapParser` (`backend/app/services/battlemap_parser.py`) extracts structured metadata from battlemap image paths. It handles the wide variety of naming conventions used by different map creators.

## Capabilities

Given a relative path like `czepeku/Island Fort/Gridded/IslandFort_Night_Rain_30x30.jpg`, the parser extracts:

| Field | Value | Source |
|-------|-------|--------|
| `author` | `"czepeku"` | First path component |
| `variant_group_name` | `"Island Fort"` | Second path component (folder) |
| `group_from_folder` | `true` | Group came from folder hierarchy |
| `sub_variants` | `["Gridded"]` | Intermediate folders between group and file |
| `sub_variant` | `"Gridded"` | Joined sub_variants string |
| `gridded` | `true` | Keyword detection in filename |
| `grid_width` | `30` | NxN dimension pattern |
| `grid_height` | `30` | NxN dimension pattern |
| `tags` | `[{category: "lighting", value: "night"}, {category: "weather", value: "rain"}]` | Vocabulary match |
| `filename` | `"IslandFort_Night_Rain_30x30.jpg"` | Path leaf |

## Parsing Pipeline

### 1. Author Detection
- Default: `parts[0]` (first folder in relative path)
- Override: `byAuthor` pattern in filename (e.g. `byJohnSmith` → `"JohnSmith"`)

### 2. Grid Detection
- CamelCase-split + normalize the filename stem to space-separated words
- Check negative regex: `\b(no[-_ ]?grid|gridless|ungridded)\b` → `gridded = False`
- Check positive regex: `\b(grid(ded)?)\b` → `gridded = True`
- Also checks path components if filename doesn't match
- Grid dimensions: `(\d{1,3})\s*[xX]\s*(\d{1,3})` pattern → `grid_width`, `grid_height`

### 3. Folder Hierarchy Parsing

The parser interprets path structure as: `author / [generic...] / group / [sub-variants...] / file`

**Generic folders** are skipped when searching for the variant group folder. The set includes:
- Platform folders: `vtt`, `roll20`, `fvtt`, `foundry`
- Resolution folders: `full resolution`, `high res`, `low res`
- Grid folders: `gridded`, `gridless`, `no grid`
- Utility folders: `singletons`, `variants`, `assets`, `originals`, `preview`, etc.

**Logic:**
1. Skip consecutive generic folders after `parts[0]` (author)
2. First non-generic folder = variant group → `group_from_folder = True`
3. Remaining intermediate folders = sub-variants
4. If ALL intermediate folders are generic → top folder IS the group (cleaned of dimensions/tier info), author = None
5. If group name resolves to a generic folder name or "Unknown" → fall back to filename stem (split at first separator) → `group_from_folder = False`

### 4. Tag Extraction

**Vocabulary:** Loaded from `TagCategory` table at init time. Each word maps to `(category, canonical_value)`. Aliases (e.g. "rainy" → "rain") are flattened into the same lookup.

**Process:**
1. Build exclusion set: author tokens, group tokens, sub-variant tokens, grid words, junk words, dimension numbers
2. Extract words from filename stem:
   - Protect bracketed content `[like this]` or `(like this)` as multi-word phrases
   - CamelCase split → space-separated
   - Replace `_`, `-` with spaces
   - Filter: min 3 chars, not in exclusions, not pure digits
3. Match words against vocabulary → categorized tag dicts with confidence 0.9
4. Also extract from path components (not filename) at confidence 0.7
5. Merge: filename tags take priority over path tags (by category+value key)

### 5. CamelCase Handling

`_split_camel()` inserts spaces at:
- `lowercase → Uppercase` transitions
- `letter → digit` and `digit → letter` transitions

Ordinals (1st, 2nd, 3rd) are protected from splitting via placeholder substitution.

Example: `AbandonedCampsiteNight30x30` → `Abandoned Campsite Night 30 x 30`

## Variant Group Detection (`group_files()`)

Used by the web import to group uploaded files into variant groups.

### Pass 1: Folder-based grouping
- Run `parse()` on each file
- Group files with `group_from_folder=True` by `(author, variant_group_name)`

### Pass 1.5: Sub-variant folder merging
When multiple folder-based groups share the same top-level folder (author), check if any group name is a subset of the top folder name's tokens. If so, the top folder is the real variant group and the subfolders are sub-variants → merge into one group.

**Example:**
```
Abandoned Campsite 30x30/Abandoned Campsite/{files}  → group "Abandoned Campsite"
Abandoned Campsite 30x30/Eerie/{files}               → merged, sub_variant "Eerie"
Abandoned Campsite 30x30/Sunset/{files}               → merged, sub_variant "Sunset"
```

### Pass 2: Prefix-based merging
For files where `group_from_folder=False`:
1. Group by parent folder
2. Within each folder, sort by filename stem
3. Compute common prefix (word-boundary-aware, respects CamelCase)
4. Merge if common prefix ≥ 6 characters; tighten prefix on each merge
5. Multi-file groups use the common prefix as group name

## Junk Words

Words filtered out during tag extraction (not meaningful as tags):
- File artifacts: `jpg`, `png`, `webp`, `vtt`, `ppi`, `dpi`, `copy`, `final`, `hd`
- Filler: `no`, `the`, `and`, `of`, `with`, `by`, `for`, `in`
- Generic map: `map`, `battlemap`, `tile`, `variation`, `variant`, `alternate`, `base`, `geomorph`
