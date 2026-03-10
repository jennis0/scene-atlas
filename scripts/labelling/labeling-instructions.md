# Image Labeling Instructions

You are labeling tabletop RPG images with a **type** and a **one-sentence description**. This document contains everything you need. Read it fully before starting.

## Setup

- **Prep directory**: `{prep-dir}` (thumbnails and batch files)
- **Run directory**: `{run-dir}` (where you write labels)
- **Source images**: `{source-dir}`

**IMPORTANT**: Only one agent may work on a run at a time. Do not run concurrently with another agent on the same run directory.

---

## Type Definitions

Every image must be classified as exactly one of these types:

| Type | Definition | Visual indicators |
|---|---|---|
| **battlemap** | Top-down or isometric view of a location sized for tactical encounters where exact positioning matters | Grid overlays, clear terrain boundaries, encounter-scale area (a room, clearing, ship deck). **Gridless versions of battlemaps are still battlemaps** — if the scene is encounter-scale and top-down, it's a battlemap regardless of whether a grid is drawn on. |
| **scene** | Artwork that illustrates a location or moment but isn't usable as a playable map | Perspective/3D-rendered views, display/showcase images, splash art. These show a location but from an angle or style that couldn't be used for tactical play. |
| **map** | Top-down or isometric view that is either imprecise (rough sketch) or shows a scale too large for tactical play | City maps, regional maps, world maps, rough pen-and-ink sketches of locations. The key distinction from battlemap: either too large-scale or too imprecise for tactical positioning. |
| **other** | Non-map content | Tokens (circular character/creature images), stat blocks, individual objects/assets (shields, sails, decorations), text overlays, marketing materials. |

### Decision Tree for Ambiguous Cases

1. Is it a top-down or isometric view? **No** → `scene`
2. Is it an individual object, token, or non-location content? **Yes** → `other`
3. Could you place miniatures on it for a tactical encounter? **No** → is it a large-scale overview (city/region)? **Yes** → `map`. Otherwise → `scene`
4. Is it encounter-scale with clear terrain? **Yes** → `battlemap`
5. Is it a rough sketch of an encounter-scale area? → `map`

If you are **genuinely unsure** after this decision tree, use the AskUserQuestion tool to ask the user. Do not guess.

---

## Description Guidelines

Write **one sentence** per image that describes what you SEE. Descriptions should be useful for searching.

### What to Include
- Terrain type (desert, forest, cave, ocean, urban, etc.)
- Key structures (bridge, castle, temple, ship, etc.)
- Notable objects or creatures (skeletons, crystals, statues, etc.)
- Atmosphere or conditions (rain, night, lava, snow, etc.)
- Layout features (islands, rivers, cliffs, rooms, etc.)

### What NOT to Include
- Whether it has a grid overlay
- Artist attribution or watermarks
- The word "battlemap", "map", or "scene" — the type field handles that
- Generic filler like "detailed fantasy" or "high quality"

### Examples

**Good descriptions:**
- "The corpse of a massive serpent with scaled hide laid across turquoise water, with wooden bridges connecting rocky islands around the creature"
- "A desert excavation site with two massive beast skeletons partially buried in sand, surrounded by rocky cliff edges"
- "A fortified lakeside castle with stone walls and multiple towers connected by a bridge to a forested shoreline"
- "A small cluttered library interior with overflowing bookshelves along the walls, reading tables, and scattered books"
- "A volcanic island with a glowing central crater spewing molten lava, surrounded by lush green vegetation and turquoise ocean"

**Bad descriptions:**
- "Desert boneyard battlemap" — too generic, doesn't describe what you see
- "A detailed fantasy battlemap showing a desert area with bones" — describes the medium, not the content
- "Avernus map with blue color scheme" — derived from filename, not visual content
- "Interior building layout" — could describe anything
- "A hellish infernal landscape for tactical encounters" - describes being a battlemap, not the content

---

{personality-section}

## Step-by-Step Workflow

Repeat this loop until all batches are done or you're running low on context:

### Step 1: Check Status
```
uv run scripts/label_images.py status --prep-dir {prep-dir} --run-dir {run-dir}
```
This tells you which batch to work on next and lists the remaining images in that batch.

### Step 2: Read the Batch File
Read the batch file from `{prep-dir}/batches/<batch-file>` to get the list of relative paths.

### Step 3: Read Thumbnails
For each relative path in the batch, the thumbnail is at:
```
{prep-dir}/thumbnails/<thumbnail_name>
```
Where `<thumbnail_name>` is the relative path with `/` replaced by `__`.

Examples:
- `Avernus.jpg` → `{prep-dir}/thumbnails/Avernus.jpg`
- `subfolder/Map.jpg` → `{prep-dir}/thumbnails/subfolder__Map.jpg`

Read up to 10 thumbnails in parallel using the Read tool.

### Step 4: Write Labels
For each image you've looked at, determine the type and write a description. Append all labels for this batch to `{run-dir}/labels.jsonl`.

Each line must be a valid JSON object:
```json
{"relpath": "Avernus.jpg", "type": "battlemap", "description": "A hellish infernal landscape with demonic structures, lava flows, and winding dark rivers between jagged rocky terrain"}
```

Fields:
- `relpath`: The relative path exactly as it appears in the batch file
- `type`: One of `battlemap`, `scene`, `map`, `other`
- `description`: One sentence describing what you see

### Step 5: Handle Uncertainty
If a thumbnail is **unreadable** (Read tool fails), or you **cannot determine** what the image shows, write to `{run-dir}/uncertain.jsonl` instead:
```json
{"relpath": "SomeImage.png", "reason": "Thumbnail could not be read by the Read tool"}
```

If you're unsure about the **type** but can see the image clearly, use AskUserQuestion to ask the user.

### Step 6: Continue or Stop
Run `status` again. If more batches remain and you have context budget, go back to Step 2 with the next batch.

When stopping (context running low or all done), report:
- How many images you labeled this session
- Which batch you stopped at
- Any issues encountered

---

## Label Format Reference

**labels.jsonl** — one JSON object per line:
```
{"relpath": "Avernus.jpg", "type": "battlemap", "description": "..."}
{"relpath": "Avernus_Blue.jpg", "type": "battlemap", "description": "..."}
```

**uncertain.jsonl** — one JSON object per line:
```
{"relpath": "SomeImage.png", "reason": "Thumbnail could not be read"}
```

Do NOT include trailing commas. Each line must be independently valid JSON.
