# Image Labeling Instructions

You are labeling tabletop RPG images with a **type**, **grid type**, and **four distinct descriptions**. This document contains everything you need. Read it fully before starting.

## Setup

- **Prep directory**: `{prep-dir}` (thumbnails and batch files)
- **Run directory**: `{run-dir}` (where you write labels)

**IMPORTANT**: Only one agent may work on a run at a time. Do not run concurrently with another agent on the same run directory.

**IMPORTANT**: Image identifiers in batch files are anonymous UUIDs, not filenames. Do not attempt to infer anything about the image from the identifier — describe only what you see in the thumbnail.

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

## Descriptions: Four Distinct Styles

You will write **four different descriptions** per image, each with a different purpose and style.

| Field | Style | Purpose | Character |
|---|---|---|---|
| `description_standard` | Full sentence, 8–25 words | Primary visual description | Rich, specific, detailed |
| `description_alt` | Full sentence, 8–25 words | Alternative description with different vocabulary | Same detail level, deliberately different word choices |
| `description_search` | Comma-separated keywords, 5–10 items | Optimized for search matching | Terse, keyword-dense, no grammar |
| `description_terse` | Single short noun phrase, 2–5 words | Quick reference | Minimal, captures the essence |

### Length Guidance

Descriptions should be **as long as they need to be**. A complex multi-room dungeon might need 20+ words; a simple grass clearing might only need 8–10. Don't pad simple images with filler to reach a word count.

### The `description_alt` Rule

The `description_alt` must describe the **same scene** as `description_standard` but use **different nouns and adjectives**. Imagine a different person describing the same image who would naturally use different words.

**Good vocabulary swaps:**
- "castle" → "keep", "fortress", "stronghold"
- "forest" → "woodland", "grove", "timberland"
- "cave" → "cavern", "grotto", "hollow"
- "path" → "trail", "track", "lane"
- "dark" → "shadowed", "dim", "gloomy"
- "stone" → "masonry", "granite", "hewn blocks"
- "large" → "vast", "sprawling", "imposing"

### Example Sets

Study these examples to understand the contrast between styles. Each example shows the same image described four different ways.

**Example 1: Lakeside Castle**
```
description_standard: "A fortified stone castle on a lakeside shore with multiple towers, crenellated walls, and a drawbridge entrance, surrounded by dense forested hills beyond a calm blue lake"
description_alt:      "A medieval keep with parapets and watchtowers perched beside still waters, its portcullis gateway flanked by wooded ridges rising beyond the shoreline"
description_search:   "castle, lake, stone walls, towers, crenellations, drawbridge, forest, water"
description_terse:    "a lakeside castle"
```

**Example 2: Lava-Filled Cavern**
```
description_standard: "A subterranean cavern with a river of molten lava flowing through the center, stone bridges spanning the glowing flow, and natural stalactites hanging from the ceiling"
description_alt:      "An underground grotto split by a channel of magma, with rock archways crossing the molten stream and mineral spires descending from the vault above"
description_search:   "cave, lava, underground, stalactites, stone bridges, volcanic, molten rock, glow"
description_terse:    "a lava-filled cavern"
```

**Example 3: Village Market Square**
```
description_standard: "A muddy cobblestone street in a small timber-framed village, with market stalls lining both sides and a stone well in the center square beneath overcast gray skies"
description_alt:      "A rain-soaked hamlet plaza paved in rough flagstones, flanked by wooden-beamed shopfronts with awnings, a drinking fountain at its heart under heavy clouds"
description_search:   "village, market square, cobblestone, timber buildings, stalls, well, mud, overcast"
description_terse:    "a village market square"
```

**Example 4: Dense Forest Path**
```
description_standard: "A narrow winding path through an ancient forest with massive trees on either side, undergrowth of ferns and vines, dappled sunlight filtering through the dense green canopy"
description_alt:      "A twisting trail beneath towering old-growth hardwoods, the floor thick with bracken and creepers, shafts of light breaking through the leafy roof overhead"
description_search:   "forest, path, ancient trees, ferns, vines, undergrowth, dense, sunlight, wilderness"
description_terse:    "a forest path"
```

**Example 5: Dungeon Corridor**
```
description_standard: "A stone-walled underground corridor with carved pillars supporting a vaulted ceiling, iron torch sconces on the walls, and a heavy wooden door in an arched alcove"
description_alt:      "A dim masonry passage lined with sculpted columns holding up a ribbed roof, wrought-iron brackets for torches, and a reinforced oak gate recessed into the far wall"
description_search:   "dungeon, corridor, stone walls, pillars, vaulted ceiling, torch sconces, wooden door, underground"
description_terse:    "a dungeon corridor"
```

**Example 6: Desert Oasis**
```
description_standard: "A verdant oasis in arid desert with palm trees surrounding a blue water pool, sand dunes rising high beyond, and scattered rocks and vegetation"
description_alt:      "A lush watering hole ringed by date palms amid parched wasteland, golden sand ridges climbing in the background with sparse scrub and boulders nearby"
description_search:   "oasis, desert, palm trees, water pool, sand dunes, rocks, vegetation, arid"
description_terse:    "a desert oasis"
```

**Example 7: Rocky Mountain Peak**
```
description_standard: "A jagged mountain peak with exposed gray rock faces, patches of snow in crevices, sparse alpine vegetation clinging to slopes, and distant mountains beyond"
description_alt:      "A craggy summit of bare granite with ice wedged into fissures, hardy scrub rooted on the inclines, and a panorama of far-off ridgelines stretching away"
description_search:   "mountain, peak, rocky, snow, alpine, exposed rock, vista, peaks in distance"
description_terse:    "a mountain peak"
```

**Example 8: Ruined Temple**
```
description_standard: "An overgrown jungle temple with vine-covered stone columns, crumbling masonry walls, scattered broken statuary partially buried in vegetation"
description_alt:      "A decaying rainforest shrine with creeper-draped pillars, eroding brickwork, and fragments of shattered idols half-swallowed by tropical undergrowth"
description_search:   "temple, ruins, jungle, stone columns, vines, overgrown, statues, crumbling stone"
description_terse:    "a ruined jungle temple"
```

**Example 9: Ship Deck**
```
description_standard: "The wooden deck of a sailing ship with coiled ropes, barrel stacks, a wheel house at the stern, mast rigging overhead, and churning dark water at the railings"
description_alt:      "A timber-planked vessel topside with bundled lines, cask piles, the helm station aft, canvas and cordage aloft, and rough seas visible past the gunwales"
description_search:   "ship, deck, wooden, ropes, barrels, mast, rigging, water, sailing"
description_terse:    "a ship deck"
```

**Example 10: Arctic Tundra**
```
description_standard: "A frozen arctic landscape with snow-covered ground stretching to the horizon, bare rock outcroppings jutting through white drifts, and sparse vegetation"
description_alt:      "An ice-bound polar expanse of windswept snowfields reaching into the distance, exposed stone ridges breaking through the blanket of white, with stunted scrub"
description_search:   "tundra, arctic, snow, ice, frozen, bare rock, sparse vegetation, mountains, desolate"
description_terse:    "an arctic tundra"
```

**Example 11: Tavern Interior**
```
description_standard: "A cozy tavern interior with a wooden bar counter, shelves of bottles and glasses behind the bar, a large hearth with a roaring fire, wooden tables and chairs, and low timber-beamed ceiling"
description_alt:      "A warm inn common room featuring a long serving bench, racks of spirits and tankards on the back wall, a broad fireplace ablaze, scattered dining furniture, and heavy rafters overhead"
description_search:   "tavern, interior, bar, bottles, hearth, fire, wooden tables, low ceiling, cozy"
description_terse:    "a tavern interior"
```

**Example 12: Swamp**
```
description_standard: "A murky swampland with dark water, gnarled dead trees rising from the mire, thick hanging vines and moss-covered branches, and dense fog hovering above"
description_alt:      "A stagnant bogland of brackish pools, twisted skeletal trunks jutting from the fen, draped curtains of lichen and algae-slicked limbs, with low-lying haze"
description_search:   "swamp, murky water, dead trees, vines, moss, lily pads, fog, vegetation, desolate"
description_terse:    "a swamp"
```

**Example 13: City Rooftop**
```
description_standard: "A sprawling city rooftop view with tiled and shingled rooftops, smoking chimneys, crowded buildings packed densely together, and narrow alleyways visible between structures"
description_alt:      "An urban skyline of terracotta and slate canopies, belching flues, tightly clustered dwellings shoulder to shoulder, with slim passages threaded between them"
description_search:   "city, rooftops, buildings, chimneys, crowded, urban, alleyways, skyline"
description_terse:    "a city rooftop"
```

**Example 14: Planar Void**
```
description_standard: "A surreal planar landscape with floating islands of rocky terrain suspended in a void of swirling purple and blue energy, crystalline formations sprouting from surfaces"
description_alt:      "An otherworldly expanse of drifting rock fragments hanging in a maelstrom of violet and indigo force, with gemstone growths erupting from the landmasses"
description_search:   "planar, void, floating islands, purple, blue energy, crystals, geometric, surreal, impossible"
description_terse:    "a planar void"
```

**Example 15: Underground Lake**
```
description_standard: "A vast underground chamber with a still dark lake occupying the floor, natural stone pillars supporting a high cavern ceiling covered in sparkling mineral deposits"
description_alt:      "An immense subterranean hall with a motionless black pool filling the basin, rough-hewn columns bracing a lofty rock vault encrusted with glittering crystal formations"
description_search:   "underground, cavern, lake, stone pillars, cave ceiling, mineral formations, bioluminescence, dark water"
description_terse:    "an underground lake"
```

**Example 16: Simple Grass Clearing** *(shorter descriptions for visually simple images)*
```
description_standard: "A flat grassy clearing with a few scattered boulders and a single large oak tree"
description_alt:      "An open meadow dotted with rocks beneath a solitary spreading hardwood"
description_search:   "grass, clearing, boulders, oak tree, open field"
description_terse:    "a grassy clearing"
```

**Example 17: Empty Stone Room** *(shorter descriptions for visually simple images)*
```
description_standard: "A bare square chamber with flagstone flooring and plain gray walls"
description_alt:      "An unadorned rectangular room paved in flat slabs with featureless masonry sides"
description_search:   "room, stone, empty, chamber, dungeon, flagstone"
description_terse:    "an empty stone room"
```

---

## Common Mistakes to Avoid

### Banned Openings

Do NOT start every description with the same formulaic phrase. These are **banned as default openings**:
- "A top-down view of..." — only use when the overhead perspective is genuinely the most noteworthy thing about the image
- "A perspective view of..."
- "An encounter-scale..."

**Instead**, lead with the most distinctive feature of the image. A cave with lava? Start with the lava. A ship in a storm? Start with the storm.

### Banned Padding

Do NOT include any of the following phrases. They add no descriptive value — the `type` field already captures this information:
- "suitable for tactical encounters"
- "unsuitable for tactical grid-based play"
- "creating an encounter-scale location"
- "arranged for tactical play"
- "rendered in perspective"
- Any phrasing about whether the image is or isn't suitable for play

### Negative Examples

```
BAD:  "A top-down view of a gridless bandit den with wooden structures, multiple interconnected rooms, water features, and scattered furnishings arranged for tactical encounter scenarios"
GOOD: "Rough-hewn wooden rooms carved into a cave wall, with sleeping cots, stacked barrels, and a narrow stream running along one edge"

BAD:  "A majestic fantasy cityscape rendered in perspective showing towering spires unsuitable for tactical grid-based play"
GOOD: "Soaring white spires and blue-domed towers rise above cascading waterfalls, lit by a dramatic golden sky"

BAD:  "A top-down encounter-scale location featuring a crystal mine entrance with large blue crystal formations emerging from green forest terrain"
GOOD: "Brilliant blue crystals jut from mossy rock around a dark mine entrance, hemmed in by dense forest on all sides"
```

---

## Varying Your Vocabulary

Use varied vocabulary across descriptions and across images. Here are common terms and alternatives — use whichever fits best, but don't default to the same word every time:

- castle → keep, fortress, stronghold, citadel, bastion
- forest → woodland, grove, thicket, timberland, copse
- cave → cavern, grotto, hollow, burrow, delve
- path → trail, track, passage, lane, route
- dark → shadowed, dim, murky, gloomy, unlit
- stone → rock, masonry, granite, hewn blocks, flagstone
- large → vast, sprawling, towering, imposing, massive
- water → pool, pond, stream, channel, basin
- old → ancient, weathered, crumbling, timeworn, aged
- small → cramped, modest, compact, narrow, tight

This is guidance, not prescription — the right word depends on context.

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
- Information inferred from the image identifier — describe only what you see

### Style Notes

**description_standard:**
- Write as a complete sentence or two
- 8–25 words depending on image complexity
- Include substantive detail: what do you actually see?
- Avoid generic adjectives; be specific about what is present

**description_alt:**
- Same length and detail level as standard
- **Must use different nouns and adjectives** from `description_standard`
- Imagine a different person describing the same image with their own vocabulary
- Do NOT simply rearrange the words from `description_standard`

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
This tells you which batch to work on next and lists the remaining images in that batch. Note: there is a built-in cooldown between status calls to prevent API rate limiting.

### Step 2: Read the Batch File
Read the batch file from `{prep-dir}/batches/<batch-file>` to get the list of image identifiers.

### Step 3: Read Thumbnails
Each entry in the batch file is a thumbnail filename. Read the thumbnail directly at:
```
{prep-dir}/thumbnails/<entry>
```

For example, if the batch file contains `a1b2c3d4e5f6.jpg`, read:
```
{prep-dir}/thumbnails/a1b2c3d4e5f6.jpg
```

Read up to 10 thumbnails in parallel using the Read tool.

### Step 4: Write Labels
For each image you've looked at, determine the type, grid type, and write four descriptions. Append all labels for this batch to `{run-dir}/labels.jsonl`.

Each line must be a valid JSON object with **seven required fields**:
```json
{
  "relpath": "a1b2c3d4e5f6.jpg",
  "type": "battlemap",
  "grid": "square",
  "description_standard": "A hellish infernal landscape with demonic structures, lava flows, and winding dark rivers between jagged rocky terrain",
  "description_alt": "A blasted wasteland of fiendish towers, molten channels, and snaking black waterways cutting through serrated stone",
  "description_search": "hell, infernal, lava, demonic, dark rivers, rocky, jagged terrain",
  "description_terse": "a hellish infernal landscape"
}
```

Fields:
- `relpath`: The image identifier exactly as it appears in the batch file
- `type`: One of `battlemap`, `scene`, `map`, `other`
- `grid`: One of `square`, `hex`, `none`
- `description_standard`: Full-sentence comprehensive description
- `description_alt`: Full-sentence alternative description with different vocabulary
- `description_search`: Comma-separated keywords and phrases
- `description_terse`: Single short noun phrase

### Step 5: Handle Uncertainty
If a thumbnail is **unreadable** (Read tool fails), or you **cannot determine** what the image shows, write to `{run-dir}/uncertain.jsonl` instead:
```json
{"relpath": "a1b2c3d4e5f6.jpg", "reason": "Thumbnail could not be read by the Read tool"}
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
{"relpath": "a1b2c3d4e5f6.jpg", "type": "battlemap", "grid": "square", "description_standard": "...", "description_alt": "...", "description_search": "...", "description_terse": "..."}
{"relpath": "b7c8d9e0f1a2.png", "type": "scene", "grid": "none", "description_standard": "...", "description_alt": "...", "description_search": "...", "description_terse": "..."}
```

**uncertain.jsonl** — one JSON object per line:
```
{"relpath": "c3d4e5f6a7b8.jpg", "reason": "Thumbnail could not be read"}
```

Do NOT include trailing commas. Each line must be independently valid JSON.
