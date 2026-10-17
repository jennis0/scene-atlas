# ImageParser — Metadata Extraction

## Overview

`ImageParser` (`backend/app/services/image_parser.py`) extracts structured metadata from image paths. It handles the wide variety of naming conventions used by different map creators.

## Capabilities

Given a relative path like `czepeku/Island Fort/Gridded/IslandFort_Night_Rain_30x30.jpg`, the parser extracts:

| Field | Value | Source |
|-------|-------|--------|
| `author` | `"czepeku"` | First path component |
| `group_name` | `"Island Fort"` | Second path component (folder) |
| `group_from_folder` | `true` | Group came from folder hierarchy |
| `subgroups` | `["Gridded"]` | Intermediate folders between group and file |
| `subgroup` | `"Gridded"` | Joined subgroups string |
| `gridded` | `true` | Keyword detection in filename |
| `grid_width` | `30` | NxN dimension pattern |
| `grid_height` | `30` | NxN dimension pattern |
| `tags` | `[{category: "lighting", value: "night"}, {category: "weather", value: "rain"}]` | Vocabulary match |
| `name` | `"Night Rain"` | Display name for the individual image |
| `filename` | `"IslandFort_Night_Rain_30x30.jpg"` | Path leaf |

## Parsing Pipeline

### 1. Author Detection
- Default: `parts[0]` (first folder in relative path)
- Override: `byAuthor` pattern in filename (e.g. `byJohnSmith` → `"JohnSmith"`, `ArenabyUpsetti` → `"Upsetti"`, `byZachari43` → `"Zachari43"`). The author must start with a capital and stops before a further `by<Capital>`. `_author_from_stem` rejects a candidate when:
  - it is a junk/filler word (`StoneCircleByTheWater`);
  - the "by" ends an ordinary word in `_by_words` (`RubyGhost`, `BabyRhinos`).
  Lowercase continuations never match (`Abyssal`, `Labyrinth`, `bystedt`). Before 2026-10 these produced authors like "ssal" and "rinth" on 200+ real files.

### 2. Grid Detection (battlemaps only)

<a id="grid-detection"></a>

**Filename-based** (always runs, in `ImageParser.parse()`):
- CamelCase-split + normalize the filename stem to space-separated words
- Check negative regex: `\b(no[-_ ]?grid|gridless|ungridded|gl)\b` → `gridded = False`
- Check hex regex: `\b(hexgrid|hex[-_ ]?grid|hex|hg)\b` → `gridded = True, grid_type = "hex"`.
  - A bare `hex` counts, because partyoftwo marks its hex maps `HexH` / `HexV` (flat/pointy) plus a line colour, e.g. `…_Online_HexHBlack`.
  - `GH` counts in the filename only. In folder names it appears as an unrelated code (a portrait pack's Gnome/Halfling `GH-GH-MS-F101`).
  - Checked against 179k real paths: 262 files newly become hex, all genuine hex maps apart from one item image (`washer-hex-…`), which is imported as a scene and so never gets grid detection.
- Check positive regex: `\b(grid(ded)?|gd)\b` → `gridded = True`
- Also checks path components if filename doesn't match
- Grid dimensions: `(\d{1,3})\s*[xX]\s*(\d{1,3})` pattern → `grid_width`, `grid_height` in name order. The parser has only the path, so it cannot tell columns from rows.
  - **Orientation is settled at ingest** (`orient_grid` in `backend/pipeline/filename_grid.py`), once the pixel size is known. `grid_width` is the column count. If the longer side of the NxM does not lie along the longer side of the image, the pair is swapped. For example, `…16x12` on a 3600×4800 portrait map is stored as 12 columns × 16 rows, which gives square 300 px cells.
  - Images within 2% of square keep the name's order.
  - Survey of the real library (2026-10): about 2.4% of non-square NxM names are rows-first. Partyoftwo, caeora and some czepeku files write them that way.
  - **Glued-on digits.** A 3-digit side may carry a digit from the name: `Destroyed630x50` is variant 6 at 30x50, `Frozenpass218X27` is Frozen Pass 2 at 18x27, and `ForestCamp25x201` is part 1 at 25x20.
    - The parser keeps the literal reading. It also lists `grid_size_alternatives`, which are the readings with one digit dropped (the leading digit on the left, the trailing digit on the right).
    - Ingest (`backend/pipeline/filename_grid.py`) switches to an alternative only when the literal size gives cells more than 1.5× from square for the image and the alternative is within 1.25×.
    - The size-only detector also gets the alternatives as sibling candidates.
    - Survey of 282 real files with a 3-digit side: 172 changed, mostly spellarena. The chosen readings measured 1.00–1.17 and the literal ones 1.82 or more. Genuine sizes (100x100, 70x108, 137x49) fit as read and are kept.
  - Migration 026 applied both rules to existing exact file-name sizes. Stored sizes were still in name order, so the alternatives could be rebuilt from them.
  - Known parser gaps:
    - Random-ID filenames such as `4x8ogd.jpg`.
    - Pack-level sizes on a single piece: `ForestPond30x28…Left` is half of the map.
- **Skipped for `image_type="scene"`** — scenes do not use grid metadata

**Image-analysis-based** (during ingest, `_detect_grid` in `backend/pipeline/ingest_process.py`):
- Enabled with the app setting `enable_image_grid_detection` (seeded `true`).
- Runs only for battlemaps (not scenes), and not for videos.
- Decision tree:
  - Filename says "no grid", or gives an exact NxM → trust it and skip analysis.
  - Filename says "grid" but gives no size → **size only**. Grid sizes from other file names in the same import group are scored as candidates, never taken as truth.
  - No keyword → **presence + size**.
- Detector: v3 for images whose longest side is 1000 px or more; the legacy detector (`backend/app/services/grid_detector.py`) below that. Analysis is at full resolution unless `grid_analysis_max_dim` is set. See [grid-detection-v3.md](grid-detection-v3.md) and ADR-019.
- Outputs:
  - `gridded`, `grid_type` (`square` / `hex`) and `grid_width` / `grid_height` (tile counts);
  - `grid_confidence`: the model's probability;
  - `grid_source`: `filename` / `detector`, set to `user` when the grid is edited by hand. Re-detection never overwrites `user`.
- Service: `backend/app/services/grid/` (`detect_grid`). Task: `backend/pipeline/tasks/grid_detection.py`. Backfill for existing images: `uv run python -m backend.pipeline.backfill_grid_detection`.

### 3. Folder Hierarchy Parsing

The parser interprets path structure as: `author / [generic...] / group / [subgroups...] / file`

**Generic folders** are skipped when searching for the image group folder. The set includes:
- Platform folders: `vtt`, `roll20`, `fvtt`, `foundry`
- Resolution folders: `full resolution`, `high res`, `low res`
- Grid folders: `gridded`, `gridless`, `no grid`
- Utility folders: `singletons`, `variants`, `assets`, `originals`, `preview`, etc.

**Logic:**
1. Skip consecutive generic folders after `parts[0]` (author)
2. First non-generic folder = image group → `group_from_folder = True`
3. Remaining intermediate folders = subgroups, with two adjustments:
   - Leading folders that clean to the group name are dropped. Packs often nest a copy of their own folder (`Pack [30x40] - $5 Rewards/Pack [30x40] - $5 Rewards/Gridless`).
   - Each remaining folder is lightly cleaned by `_clean_subgroup`, which removes only dimensions, pricing and the brackets they leave empty. Grid words and numbering are kept, because they are meaningful subgroup labels.
4. If ALL intermediate folders are generic → top folder IS the group (cleaned of dimensions/tier info), author = None
5. If group name resolves to a generic folder name or "Unknown" → fall back to filename stem (split at first separator) → `group_from_folder = False`

### 4. Tag Extraction

**Vocabulary:** Loaded from `TagCategory` table at init time. Each word maps to `(category, canonical_value)`. Aliases (e.g. "rainy" → "rain") are flattened into the same lookup.

**Process:**
1. Build exclusion set: author tokens, group tokens, subgroup tokens, grid words, junk words, dimension numbers
2. Extract words from filename stem:
   - Protect bracketed content `[like this]` or `(like this)` as multi-word phrases
   - CamelCase split → space-separated
   - Replace `_`, `-` with spaces
   - Filter: min 3 chars, not in exclusions, not pure digits
3. Match words against vocabulary → categorized tag dicts with confidence 0.9
4. Also extract from path components (not filename) at confidence 0.7
5. Merge: filename tags take priority over path tags (by category+value key)

### 5. Name Cleaning (`_clean_group_name`, `_build_name`)

The parser generates two cleaned names:

**Group name** (`_clean_group_name`): The "proper name" of the image group (map collection), with noise stripped.

Removals (in order):
1. DPI/PPI markers: `140dpi`, `70ppi`
2. Pixel dimensions: `12000x8000`
3. Grid dimensions: `30x30`
4. Tier info: `Tier 2`
5. Volume info: `Vol3`
6. Pricing: `$5 Rewards`
7. `Full Resolution` / `FR Files`
8. Platform markers: `FVTT`, `Roll20`, `R20`, `VTT`
9. `Maps` (plural only — singular `Map` preserved)
10. Grid state: `Gridded`, `Gridless`, `No Grid`, `GL`, `GD`
10a. Brackets left empty by the removals above: `Pack - $5 Rewards (Gridless)` → `Pack` rather than `Pack - ()`. Brackets that still have content, such as `[various]`, are kept.
11. Leading numbering: `07. Swamps` → `Swamps`
12. Author prefix (concatenated word matching)
13. Repeated word sequences

Formatting: underscore/slug-dash → spaces, CamelCase split, abbreviation+number rejoin (`FL 1` → `FL1`), title-case-preserve (only capitalize all-lowercase words, preserving acronyms).

**Image name** (`_build_name`): A display name for the individual image.

Steps:
1. Normalize text (underscores → spaces, CamelCase split, dash handling)
2. Strip DPI/PPI, pixel dimensions, grid dimensions
3. Strip author prefix
4. Remove `Maps` (plural)
5. Multi-word sequence deduplication
6. Strip group name prefix (always stripped)
7. Strip subgroup folder names (contiguous word-sequence matching, guarded against emptying)
8. Consecutive duplicate word removal
9. Title-case-preserve on all-lowercase results

The group name prefix and subgroup names are always stripped since names are displayed alongside their group and subgroup context. If stripping leaves an empty result, the cleaned stem is used as fallback.

**Examples:**
| Path | Group | Name |
|------|-------|------|
| `Crosshead/DUNGEONS - DRAGONGATE/Dragon Gate no light.jpg` | DUNGEONS - DRAGONGATE | Dragon Gate no light |
| `dice_grimorium/Snowy Forest Tier 2/SnowyForestTier2_FR_Gridless_R20_SnowyForest-1.jpg` | Snowy Forest | Tier 2 FR Gridless R20 - 1 |
| `mikwewa/140dpiShieldChurchMaps_140dpiChurchHeavenDayGfGrid.jpg` | Shield Church | Church Heaven Day Gf Grid |
| `moonlight_maps/Rocky Coast/MA/No Grid/Moonlight_Maps_Rocky_Coast_Lava06_18x22.jpg` | Rocky Coast | Lava 06 |

### 6. CamelCase Handling

`_split_camel()` inserts spaces at:
- `lowercase → Uppercase` transitions
- `letter → digit` and `digit → letter` transitions

Runs two passes to catch adjacent transitions (e.g. `Night3Grid` → `Night 3Grid` → `Night 3 Grid`). Ordinals (1st, 2nd, 3rd) are re-protected between passes via placeholder substitution.

Example: `AbandonedCampsiteNight30x30` → `Abandoned Campsite Night 30 x 30`

### Integration with Ingestion

In `backend/pipeline/ingest_process.py` (`commit_batch`), `Image.name` is populated from `parsed["name"]`, falling back to the import group's name, then the filename stem. This gives each image a distinct, human-readable display name separate from its group.

## Group Detection (`group_files()`)

Called at seal time (`ingest_queue.plan_job`) to group an import's files into import groups, separately per `image_type`. Groups whose `(name, author)` already exist in the gallery are merged into them; see [ingestion.md](ingestion.md#3-data-model).

### Pass 1: Folder-based grouping
- Run `parse()` on each file
- Group files with `group_from_folder=True` by `(author, group_name)`

### Pass 1.5: Subgroup folder merging
When multiple folder-based groups share the same top-level folder (author), check if any group name is a subset of the top folder name's tokens. If so, the top folder is the real image group and the subfolders are subgroups → merge into one group.

**Example:**
```
Abandoned Campsite 30x30/Abandoned Campsite/{files}  → group "Abandoned Campsite"
Abandoned Campsite 30x30/Eerie/{files}               → merged, subgroup "Eerie"
Abandoned Campsite 30x30/Sunset/{files}               → merged, subgroup "Sunset"
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

**Note:** Scenes (`image_type="scene"`) use a reduced junk word list since some map-specific junk words may be meaningful scene descriptors.

## Image Type Awareness

The parser is type-aware via the `image_type` field (default: `"battlemap"`):

| Behavior | `battlemap` | `scene` |
|----------|-------------|---------|
| Grid detection | Yes | Skipped |
| Grid dimension extraction | Yes | Skipped |
| Junk word list | Full list | Reduced list |
| Tag extraction | Full | Full |
| Name/group parsing | Full | Full |

The `image_type` is chosen per import (per file in the manifest API); see [ingestion.md](ingestion.md#7-upload-protocol). At the storage level, the `Image` model has an `image_type` column that drives conditional UI behavior (e.g., hiding the grid panel for scenes).
