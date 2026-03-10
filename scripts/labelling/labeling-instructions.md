# Image Labeling Instructions

You are labeling tabletop RPG images with a **type**, **grid type**, and **three distinct descriptions**. This document contains everything you need. Read it fully before starting.

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

## Grid Type

Identify the grid type visible on the image. Only visually inspect — do not run automated detection.

| Grid | When to use |
|------|-------------|
| `square` | Visible square or rectangular grid overlay, or strong implied grid lines |
| `hex` | Visible hexagonal grid overlay |
| `none` | No grid present, or image type is `scene`, `map`, or `other` |

**Important:** For `scene`, `map`, and `other` image types, always set `grid: "none"`. Only battlemaps should have `square` or `hex`.

---

## Descriptions: Three Distinct Styles

You will write **three different descriptions** per image, each with a different purpose and style. They must be **deliberately different** — not paraphrases of each other. They should feel like they came from three different people with different needs.

| Field | Style | Purpose | Character |
|---|---|---|---|
| `description_standard` | Full sentence, complete visual inventory | Comprehensive reference | Rich, specific, detailed |
| `description_search` | Comma-separated keywords and short phrases | Optimized for search matching | Terse, keyword-dense, no grammar |
| `description_terse` | Single short noun phrase | Quick reference | Minimal, captures the essence |

### Example Sets

Study these examples to understand the contrast between styles. Each example shows the same image described three different ways.

**Example 1: Lakeside Castle**
```
description_standard: "A fortified stone castle on a lakeside shore with multiple towers, crenellated walls, and a drawbridge entrance, surrounded by dense forested hills beyond a calm blue lake"
description_search: "castle, lake, stone walls, towers, crenellations, drawbridge, forest, water"
description_terse: "a lakeside castle"
```

**Example 2: Lava-Filled Cavern**
```
description_standard: "A subterranean cavern with a river of molten lava flowing through the center, stone bridges spanning the glowing flow, and natural stalactites hanging from the cave ceiling illuminated by orange firelight"
description_search: "cave, lava, underground, stalactites, stone bridges, volcanic, molten rock, glow"
description_terse: "a lava-filled cavern"
```

**Example 3: Village Market Square**
```
description_standard: "A muddy cobblestone street in a small timber-framed village, with market stalls lining both sides and a stone well in the center square beneath overcast gray skies"
description_search: "village, market square, cobblestone, timber buildings, stalls, well, mud, overcast"
description_terse: "a village market square"
```

**Example 4: Dense Forest Path**
```
description_standard: "A narrow winding path through an ancient forest with massive ancient trees on either side, undergrowth of ferns and vines, dappled sunlight filtering through the dense green canopy above"
description_search: "forest, path, ancient trees, ferns, vines, undergrowth, dense, sunlight, wilderness"
description_terse: "a forest path"
```

**Example 5: Dungeon Corridor**
```
description_standard: "A stone-walled underground dungeon corridor with carved pillars supporting a vaulted ceiling, iron torch sconces on the walls, and a heavy wooden door set into an arched alcove at the far end"
description_search: "dungeon, corridor, stone walls, pillars, vaulted ceiling, torch sconces, wooden door, underground"
description_terse: "a dungeon corridor"
```

**Example 6: Desert Oasis**
```
description_standard: "A verdant oasis in arid desert with palm trees surrounding a blue water pool, sand dunes rising high beyond, and scattered rocks and vegetation creating small sheltered clearings"
description_search: "oasis, desert, palm trees, water pool, sand dunes, rocks, vegetation, arid"
description_terse: "a desert oasis"
```

**Example 7: Rocky Mountain Peak**
```
description_standard: "A jagged mountain peak with exposed gray rock faces, patches of snow in crevices, sparse alpine vegetation clinging to slopes, and a wide vista of distant mountains visible beyond"
description_search: "mountain, peak, rocky, snow, alpine, exposed rock, vista, peaks in distance"
description_terse: "a mountain peak"
```

**Example 8: Ruined Temple**
```
description_standard: "An overgrown jungle temple with vine-covered stone columns, crumbling masonry walls, scattered broken statuary partially buried in vegetation, and an open-air central chamber with a decomposing roof"
description_search: "temple, ruins, jungle, stone columns, vines, overgrown, statues, crumbling stone"
description_terse: "a ruined jungle temple"
```

**Example 9: Ship Deck**
```
description_standard: "The wooden deck of a sailing ship with coiled ropes, barrel stacks, a wheel house at the stern, mast rigging overhead, and churning dark water visible at the railings"
description_search: "ship, deck, wooden, ropes, barrels, mast, rigging, water, sailing"
description_terse: "a ship deck"
```

**Example 10: Arctic Tundra**
```
description_standard: "A frozen arctic landscape with snow-covered ground stretching to the horizon, bare rock outcroppings jutting through white drifts, sparse vegetation, and pale gray sky with distant icy mountains"
description_search: "tundra, arctic, snow, ice, frozen, bare rock, sparse vegetation, mountains, desolate"
description_terse: "an arctic tundra"
```

**Example 11: Tavern Interior**
```
description_standard: "A cozy tavern interior with a wooden bar counter, shelves of bottles and glasses behind the bar, a large hearth with a roaring fire, wooden tables and chairs scattered throughout, and low timber-beamed ceiling"
description_search: "tavern, interior, bar, bottles, hearth, fire, wooden tables, low ceiling, cozy"
description_terse: "a tavern interior"
```

**Example 12: Swamp**
```
description_standard: "A murky swampland with dark water, gnarled dead trees rising from the mire, thick hanging vines and moss-covered branches, patches of lily pads and floating vegetation, and dense fog hovering above"
description_search: "swamp, murky water, dead trees, vines, moss, lily pads, fog, vegetation, desolate"
description_terse: "a swamp"
```

**Example 13: City Rooftop**
```
description_standard: "A sprawling city rooftop view with tiled and shingled rooftops, smoking chimneys, crowded buildings packed densely together, narrow alleyways visible between structures, and distant urban landscape fading into haze"
description_search: "city, rooftops, buildings, chimneys, crowded, urban, alleyways, skyline"
description_terse: "a city rooftop"
```

**Example 14: Planar Void**
```
description_standard: "A surreal planar landscape with floating islands of rocky terrain suspended in a void of swirling purple and blue energy, crystalline formations sprouting from surfaces, and strange glowing geometric shapes in the distance"
description_search: "planar, void, floating islands, purple, blue energy, crystals, geometric, surreal, impossible"
description_terse: "a planar void"
```

**Example 15: Underground Lake**
```
description_standard: "A vast underground chamber with a still dark lake occupying the floor, natural stone pillars supporting a high cavern ceiling covered in sparkling mineral deposits and formations, faint bioluminescent glowing in the distance"
description_search: "underground, cavern, lake, stone pillars, cave ceiling, mineral formations, bioluminescence, dark water"
description_terse: "an underground lake"
```

---

## Guidelines for All Descriptions

### What to Include
- Terrain type (desert, forest, cave, ocean, urban, mountain, etc.)
- Key structures (bridge, castle, temple, ship, well, etc.)
- Notable objects or features (trees, rocks, lava, water, vegetation, etc.)
- Atmosphere or conditions (rain, night, lava, snow, fog, fire, etc.)
- Layout/spatial features (islands, rivers, cliffs, rooms, corridors, etc.)

### What NOT to Include
- Whether it has a grid overlay (the `grid` field handles that)
- Artist attribution or watermarks
- The words "battlemap", "map", or "scene" — the `type` field handles that
- Generic filler like "detailed fantasy" or "high quality"
- Metadata like dimensions or file format

### Style Notes

**description_standard:**
- Write as a complete sentence or two
- Aim for ~15–25 words
- Include substantive detail: what do you actually see?
- Avoid generic adjectives; be specific about what is present

**description_search:**
- List the most important visual elements as keywords or very short phrases
- Separate with commas
- No verbs, no grammar — just the nouns and key modifiers
- Aim for 5–10 keywords
- Focus on searchable terms: what would someone type to find this image?

**description_terse:**
- A single noun phrase, as short as possible
- 2–5 words maximum
- Aim to capture the single most important thing about the image
- Examples: "a forest path", "a castle", "an underground lake", "a ship deck"

---

## Step-by-Step Workflow

Repeat this loop until all batches are done or you're running low on context:

### Step 1: Check Status
```
uv run scripts/labelling/label_images.py status --prep-dir {prep-dir} --run-dir {run-dir}
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
For each image you've looked at, determine the type, grid type, and write three descriptions. Append all labels for this batch to `{run-dir}/labels.jsonl`.

Each line must be a valid JSON object with **six required fields**:
```json
{
  "relpath": "Avernus.jpg",
  "type": "battlemap",
  "grid": "square",
  "description_standard": "A hellish infernal landscape with demonic structures, lava flows, and winding dark rivers between jagged rocky terrain",
  "description_search": "hell, infernal, lava, demonic, dark rivers, rocky, jagged terrain",
  "description_terse": "a hellish infernal landscape"
}
```

Fields:
- `relpath`: The relative path exactly as it appears in the batch file
- `type`: One of `battlemap`, `scene`, `map`, `other`
- `grid`: One of `square`, `hex`, `none`
- `description_standard`: Full-sentence comprehensive description
- `description_search`: Comma-separated keywords and phrases
- `description_terse`: Single short noun phrase

### Step 5: Handle Uncertainty
If a thumbnail is **unreadable** (Read tool fails), or you **cannot determine** what the image shows, write to `{run-dir}/uncertain.jsonl` instead:
```json
{"relpath": "SomeImage.png", "reason": "Thumbnail could not be read by the Read tool"}
```

If you're unsure about the **type** or **grid** but can see the image clearly, use AskUserQuestion to ask the user.

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
{"relpath": "Avernus.jpg", "type": "battlemap", "grid": "square", "description_standard": "...", "description_search": "...", "description_terse": "..."}
{"relpath": "Avernus_Blue.jpg", "type": "battlemap", "grid": "hex", "description_standard": "...", "description_search": "...", "description_terse": "..."}
```

**uncertain.jsonl** — one JSON object per line:
```
{"relpath": "SomeImage.png", "reason": "Thumbnail could not be read"}
```

Do NOT include trailing commas. Each line must be independently valid JSON.
