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

## What to Look For

When reviewing each label, check for these issues:

### Type Errors
- Scene labeled as battlemap (or vice versa) — check with the decision tree
- Tokens or assets labeled as anything other than `other`
- Large-scale maps (city/region) labeled as `battlemap`
- Top-down encounter-scale views labeled as `scene` or `map`

### Description Errors
- **Too generic**: "fantasy terrain", "interior layout", "volcanic landscape" — needs specific details
- **References the medium**: "A detailed battlemap showing..." or "A fantasy map of..." — describe the CONTENT not the format
- **Derived from filename**: mentions color variants, grid status, or artist names that came from the filename
- **Mentions grid overlays**: "with tactical grid overlay" — the type field handles this, descriptions should describe the scene
- **Missing key features**: if the image clearly shows a distinctive object (giant skeleton, glowing crystal, ship wreck) and the description doesn't mention it

### What a Good Description Looks Like
- One sentence, specific, search-useful
- Describes what you SEE: terrain, structures, creatures/objects, atmosphere, notable features
- Example: "A desert excavation site with two massive beast skeletons partially buried in sand, surrounded by rocky cliff edges"

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
- Is the description specific, visual, and search-useful?
- Does the description avoid the common errors listed above?

### Step 5: Write Results

**If the label is correct**, append to `{review-dir}/approved.jsonl`:
```json
{"relpath": "Avernus.jpg", "type": "battlemap", "description": "A hellish infernal landscape with demonic structures, lava flows, and winding dark rivers"}
```

**If the label needs correction**, append to `{review-dir}/corrections.jsonl`:
```json
{"relpath": "Avernus.jpg", "type": "battlemap", "description": "Corrected description here", "original_type": "map", "original_description": "Original description here", "reason": "Was classified as map but is clearly encounter-scale top-down view"}
```

### Step 6: Continue or Stop
Run `status` again. If more labels remain and you have context budget, continue from Step 2.

When stopping, report:
- How many labels you reviewed this session
- How many approved vs corrected
- Any patterns in errors you noticed

---

## Output Format Reference

**approved.jsonl** — same format as labels:
```
{"relpath": "Avernus.jpg", "type": "battlemap", "description": "..."}
```

**corrections.jsonl** — corrected label with originals and reason:
```
{"relpath": "Avernus.jpg", "type": "battlemap", "description": "corrected", "original_type": "map", "original_description": "original", "reason": "explanation"}
```

Each line must be independently valid JSON. No trailing commas.
