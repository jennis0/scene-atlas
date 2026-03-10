# Label Review Instructions

You are reviewing another agent's image labels for correctness against the labeling guidelines. This document contains everything you need. Read it fully before starting.

## Setup

- **Prep directory**: `{prep-dir}` (thumbnails and batch files)
- **Review directory**: `{review-dir}` (where you write approved/corrected labels)
- **Source images**: `{source-dir}`
- **Original labels**: `{review-dir}/original-labels.jsonl`

**IMPORTANT**: Only one agent may work on a review at a time. Do not run concurrently with another agent on the same review directory.

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

## Descriptions: Three Distinct Styles

The original agent wrote three descriptions per image. Review each one for correctness and style.

| Field | Style | Check for |
|---|---|---|
| `description_standard` | Full sentence, complete visual inventory | Specific details, not generic; mentions key structures/objects; natural language |
| `description_search` | Comma-separated keywords and short phrases | Keywords are searchable; appropriate keyword coverage; no grammar or verbs |
| `description_terse` | Single short noun phrase | Captures the essence; 2–5 words maximum |

### What to Look For

#### Common Description Errors
- **Too generic**: "fantasy terrain", "interior layout", "volcanic landscape" — needs specific details
- **References the medium**: "A detailed battlemap showing..." or "A fantasy map of..." — describe the CONTENT not the format
- **Derived from filename**: mentions color variants, grid status, or artist names that came from the filename
- **Mentions grid overlays**: "with tactical grid overlay" — the type field handles this, descriptions should describe the scene
- **Missing key features**: if the image clearly shows a distinctive object (giant skeleton, glowing crystal, ship wreck) and the description doesn't mention it

#### Standard Description Specific Errors
- Incomplete sentences or sentence fragments
- Too short (under 10 words) — should be comprehensive
- Too generic or lacking specificity

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
{"relpath": "Forest.jpg", "type": "battlemap", "grid": "none", "description_standard": "A forest", "description_search": "forest", "description_terse": "a forest"}
```

**Problem:** All three descriptions are too generic and repetitive. They're essentially paraphrases of each other.

**Corrected:**
```json
{
  "relpath": "Forest.jpg",
  "type": "battlemap",
  "grid": "none",
  "description_standard": "A narrow winding path through an ancient forest with massive old trees on either side, undergrowth of ferns and vines, dappled sunlight filtering through the dense green canopy",
  "description_search": "forest, path, ancient trees, ferns, vines, undergrowth, dense, sunlight",
  "description_terse": "a forest path",
  "original_description_standard": "A forest",
  "original_description_search": "forest",
  "original_description_terse": "a forest",
  "reason": "Original descriptions were too generic and identical in structure. Revised to add specific visual details (path, ancient trees, undergrowth, sunlight) and created distinct description styles per guidelines."
}
```

---

## Step-by-Step Workflow

Repeat this loop until all labels are reviewed or you're running low on context:

### Step 1: Check Status
```
uv run scripts/label_images.py status --prep-dir {prep-dir} --review-dir {review-dir}
```
This tells you which labels still need reviewing and lists the next batch of relpaths.

### Step 2: Read Original Labels
Read `{review-dir}/original-labels.jsonl` and find the entries for the next batch of relpaths to review.

### Step 3: Read Thumbnails
For each relpath, the thumbnail is at:
```
{prep-dir}/thumbnails/<thumbnail_name>
```
Where `<thumbnail_name>` is the relpath with `/` replaced by `__`.

Read up to 10 thumbnails in parallel using the Read tool.

### Step 4: Evaluate Each Label
For each image, compare the original label against what you see in the thumbnail:
- Is the type correct per the decision tree?
- Is the grid field correct?
- Are the three descriptions specific, distinct, and search-useful?
- Do the descriptions avoid the common errors listed above?

### Step 5: Write Results

**If the label is correct**, append to `{review-dir}/approved.jsonl`:
```json
{
  "relpath": "Avernus.jpg",
  "type": "battlemap",
  "grid": "square",
  "description_standard": "A hellish infernal landscape with demonic structures, lava flows, and winding dark rivers between jagged rocky terrain",
  "description_search": "hell, infernal, lava, demonic, dark rivers, rocky, jagged",
  "description_terse": "a hellish infernal landscape"
}
```

**If the label needs correction**, append to `{review-dir}/corrections.jsonl`:
```json
{
  "relpath": "Avernus.jpg",
  "type": "battlemap",
  "grid": "square",
  "description_standard": "Corrected standard description",
  "description_search": "corrected, search, keywords",
  "description_terse": "corrected terse description",
  "original_type": "map",
  "original_grid": "none",
  "original_description_standard": "Original standard",
  "original_description_search": "original, search",
  "original_description_terse": "original terse",
  "reason": "Type was incorrectly labeled as map; this is clearly an encounter-scale top-down view. Grid should be square, not none. Descriptions were also too generic."
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
{"relpath": "Avernus.jpg", "type": "battlemap", "grid": "square", "description_standard": "...", "description_search": "...", "description_terse": "..."}
```

**corrections.jsonl** — corrected label with originals and reason:
```
{"relpath": "Avernus.jpg", "type": "battlemap", "grid": "square", "description_standard": "corrected", "description_search": "corrected", "description_terse": "corrected", "original_type": "map", "original_grid": "none", "original_description_standard": "original", "original_description_search": "original", "original_description_terse": "original", "reason": "explanation"}
```

Each line must be independently valid JSON. No trailing commas.
