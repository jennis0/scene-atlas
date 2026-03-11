# Label Review Instructions

You are reviewing another agent's image labels for correctness against the labeling guidelines. This document contains everything you need. Read it fully before starting.

## Setup

- **Prep directory**: `{prep-dir}` (thumbnails and batch files)
- **Review directory**: `{review-dir}` (where you write approved/corrected labels)
- **Original labels**: `{review-dir}/original-labels.jsonl`

**IMPORTANT**: Only one agent may work on a review at a time. Do not run concurrently with another agent on the same review directory.

**IMPORTANT**: Image identifiers in labels are anonymous UUIDs, not filenames. Do not attempt to infer anything about the image from the identifier.

---

## Type Definitions

| Type | Definition | Visual indicators |
|---|---|---|
| **battlemap** | Top-down or isometric view of a location sized for tactical encounters where exact positioning matters | Grid overlays, clear terrain boundaries, encounter-scale area (a room, clearing, ship deck). **Gridless versions of battlemaps are still battlemaps.** |
| **scene** | Artwork that illustrates a location or moment but isn't usable as a playable map | Perspective/3D-rendered views, display/showcase images, splash art. |
| **map** | Top-down or isometric view that is either imprecise (rough sketch) or shows a scale too large for tactical play | City maps, regional maps, world maps, rough pen-and-ink sketches. |
| **other** | Non-map content | Tokens, stat blocks, individual objects/assets, text overlays. |

### Decision Tree for Ambiguous Cases

1. Is it a top-down or isometric view? **No** → `scene`
2. Is it an individual object, token, or non-location content? **Yes** → `other`
3. Could you place miniatures on it for a tactical encounter? **No** → is it a large-scale overview (city/region)? **Yes** → `map`. Otherwise → `scene`
4. Is it encounter-scale with clear terrain? **Yes** → `battlemap`
5. Is it a rough sketch of an encounter-scale area? → `map`

---

## Grid Type

Check that the grid field is correctly set:

| Grid | When to use |
|------|-------------|
| `square` | Visible square or rectangular grid overlay, or strong implied grid lines |
| `hex` | Visible hexagonal grid overlay |
| `none` | No grid present, or image type is `scene`, `map`, or `other` |

**Error to watch for:** Scene/map/other labeled with grid `square` or `hex`. These should always be `none`.

---

## Descriptions: Four Distinct Styles

The original agent wrote four descriptions per image. Review each one for correctness and style.

| Field | Style | Check for |
|---|---|---|
| `description_standard` | Full sentence, 8–25 words | Specific details, not generic; mentions key structures/objects; natural language |
| `description_alt` | Full sentence, 8–25 words, different vocabulary | Uses genuinely different nouns/adjectives from standard; not a rearrangement |
| `description_search` | Comma-separated keywords, 5–10 items | Keywords are searchable; appropriate coverage; no grammar or verbs |
| `description_terse` | Single short noun phrase, 2–5 words | Captures the essence; concise |

### What to Look For

#### Common Description Errors
- **Too generic**: "fantasy terrain", "interior layout", "volcanic landscape" — needs specific details
- **References the medium**: "A detailed battlemap showing..." or "A fantasy map of..." — describe the CONTENT not the format
- **Formulaic openings**: Every description starts with "A top-down view of..." or "A perspective view of..." — should lead with the most distinctive feature
- **Banned padding**: Contains phrases like "suitable for tactical encounters", "unsuitable for tactical grid-based play", "creating an encounter-scale location" — the `type` field handles this
- **Missing key features**: if the image clearly shows a distinctive object (giant skeleton, glowing crystal, ship wreck) and the description doesn't mention it

#### Alt Description Specific Errors
- **Same vocabulary as standard**: If `description_alt` reuses the same key nouns and adjectives as `description_standard`, it needs to be rewritten with different words
- **Just a rearrangement**: Moving words around isn't enough — genuinely different vocabulary is required

#### Standard/Alt Length Errors
- Padded with filler to reach a word count when the image is visually simple
- Too short for a complex scene (under 8 words for a multi-room dungeon)

#### Search Description Specific Errors
- Contains verbs ("has", "shows") — should be keywords only
- Missing important searchable keywords
- Too many words (looks like a badly formatted full description)

#### Terse Description Specific Errors
- More than one noun phrase (2+ sentences)
- More than 5 words
- Generic ("a location", "some scenery") instead of specific ("a forest path", "a tavern")

### Example Review

**Original labels from agent:**
```json
{"relpath": "a1b2c3d4.jpg", "type": "battlemap", "grid": "none", "description_standard": "A top-down view of a forest path arranged for tactical encounters", "description_alt": "A top-down forest path suitable for tactical play", "description_search": "forest, path, tactical", "description_terse": "a forest"}
```

**Problems:**
1. Both standard and alt use formulaic "top-down view of" openings
2. Both contain banned padding ("arranged for tactical encounters", "suitable for tactical play")
3. Alt is essentially the same as standard — no vocabulary diversity
4. Search keywords are too sparse
5. Terse is too generic ("a forest" vs "a forest path")

**Corrected:**
```json
{
  "relpath": "a1b2c3d4.jpg",
  "type": "battlemap",
  "grid": "none",
  "description_standard": "A narrow winding path through an ancient forest with massive old trees, undergrowth of ferns and vines, dappled sunlight filtering through the dense green canopy",
  "description_alt": "A twisting trail beneath towering hardwoods, the floor thick with bracken and creepers, shafts of light breaking through the leafy roof overhead",
  "description_search": "forest, path, ancient trees, ferns, vines, undergrowth, dense, sunlight, woodland",
  "description_terse": "a forest path",
  "original_description_standard": "A top-down view of a forest path arranged for tactical encounters",
  "original_description_alt": "A top-down forest path suitable for tactical play",
  "original_description_search": "forest, path, tactical",
  "original_description_terse": "a forest",
  "reason": "Descriptions used banned formulaic openings and padding. Alt lacked vocabulary diversity. Search keywords too sparse. Terse too generic."
}
```

---

## Step-by-Step Workflow

Repeat this loop until all labels are reviewed or you're running low on context:

### Step 1: Check Status
```
uv run scripts/labelling/label_images.py status --prep-dir {prep-dir} --review-dir {review-dir}
```
This tells you which labels still need reviewing and lists the next batch of identifiers.

### Step 2: Read Original Labels
Read `{review-dir}/original-labels.jsonl` and find the entries for the next batch of identifiers to review.

### Step 3: Read Thumbnails
Each image identifier in the labels is also the thumbnail filename. Read the thumbnail at:
```
{prep-dir}/thumbnails/<identifier>
```

Read up to 10 thumbnails in parallel using the Read tool.

### Step 4: Evaluate Each Label
For each image, compare the original label against what you see in the thumbnail:
- Is the type correct per the decision tree?
- Is the grid field correct?
- Are the four descriptions specific, distinct, and search-useful?
- Does `description_alt` use genuinely different vocabulary from `description_standard`?
- Do the descriptions avoid the common errors listed above?

### Step 5: Write Results

**If the label is correct**, append to `{review-dir}/approved.jsonl`:
```json
{
  "relpath": "a1b2c3d4.jpg",
  "type": "battlemap",
  "grid": "square",
  "description_standard": "...",
  "description_alt": "...",
  "description_search": "...",
  "description_terse": "..."
}
```

**If the label needs correction**, append to `{review-dir}/corrections.jsonl`:
```json
{
  "relpath": "a1b2c3d4.jpg",
  "type": "battlemap",
  "grid": "square",
  "description_standard": "Corrected standard description",
  "description_alt": "Corrected alt description with different vocabulary",
  "description_search": "corrected, search, keywords",
  "description_terse": "corrected terse",
  "original_type": "map",
  "original_grid": "none",
  "original_description_standard": "Original standard",
  "original_description_alt": "Original alt",
  "original_description_search": "original, search",
  "original_description_terse": "original terse",
  "reason": "Type was incorrectly labeled as map; this is clearly an encounter-scale top-down view."
}
```

### Step 6: Continue or Stop
Run `status` again. If more labels remain and you have context budget, continue from Step 2.

When stopping, report:
- How many labels you reviewed this session
- How many approved vs corrected
- Any patterns in errors you noticed

---

## Output Format Reference

**approved.jsonl** — same format as original labels:
```
{"relpath": "a1b2c3d4.jpg", "type": "battlemap", "grid": "square", "description_standard": "...", "description_alt": "...", "description_search": "...", "description_terse": "..."}
```

**corrections.jsonl** — corrected label with originals and reason:
```
{"relpath": "a1b2c3d4.jpg", "type": "battlemap", "grid": "square", "description_standard": "corrected", "description_alt": "corrected alt", "description_search": "corrected", "description_terse": "corrected", "original_type": "map", "original_grid": "none", "original_description_standard": "original", "original_description_alt": "original alt", "original_description_search": "original", "original_description_terse": "original", "reason": "explanation"}
```

Each line must be independently valid JSON. No trailing commas.
