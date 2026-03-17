# Tags & Filtering

Tags in Scene Atlas are organised into colour-coded categories. Each category represents a different dimension of a scene — lighting, season, weather, environment, and more. The tag system powers both visual organisation and search expansion.

## Categories

Each tag belongs to a category with a distinctive colour. The colour encodes the category, so tag pills show only the value — hover to see the category name.

| Category | Colour | Examples |
|----------|--------|----------|
| Lighting | Amber | dawn, twilight, torchlit, moonlit |
| Season | Orange | spring, summer, autumn, winter |
| Weather | Sky | rain, snow, fog, storm, clear |
| Environment | Emerald | forest, cave, ocean, mountain, desert |
| Features | Stone | bridge, river, ruins, campfire, altar |
| State | Red | abandoned, destroyed, flooded, overgrown |
| Theme | Purple | horror, magical, peaceful, ominous |
| Population | Cyan | empty, crowded, sparse |
| Perspective | Violet | top-down, isometric, side-view |
| Style | Rose | realistic, painterly, hand-drawn |

## Tag Packs

Tag packs are genre-specific vocabularies that pre-populate your categories with common values and aliases. Available packs:

- **Common** — universal terms (lighting conditions, seasons, weather)
- **Fantasy** — dungeons, taverns, enchanted forests, castles
- **Sci-Fi** — space stations, cyberpunk streets, alien landscapes
- **Cyberpunk** — neon, corporate, street-level
- **Horror** — crypts, haunted, blood, decay
- **Historical** — medieval, roman, victorian

Install packs from **Settings > Tag Packs**. Importing a pack merges new values into existing categories — it never overwrites your custom tags.

## Aliases

Aliases are synonyms that expand your searches automatically. If "rainy" is an alias for "rain", then searching for "rainy" will also find images tagged "rain" — no extra effort needed.

Aliases are defined per tag value within a category. Tag packs come with sensible aliases pre-configured, and you can add your own through the tag management UI.

## Auto-Tagging

During import, Scene Atlas extracts tags from filenames where possible. Common patterns it recognises:

- `ForestClearing_Night.jpg` → tags: "forest", "night"
- `Tavern_Snowy_Grid.jpg` → tags: "tavern", "snowy", grid detected

Auto-detected tags are marked with a confidence score. You can review and adjust them in the image viewer.

## Manual Tagging

In the image viewer, click **+ Tag** to add tags to the current image. The tag picker shows a two-level dropdown: select a category, then choose or type a value.

Tags can also be removed from the image viewer by clicking the × on any tag pill.

## Filtering by Tags

The gallery filter panel lets you filter by tags:

- **Within a category** — selections are combined with OR. Selecting "forest" and "cave" in **environment** shows images tagged with either.
- **Across categories** — selections are combined with AND. Selecting "forest" in **environment** and "night" in **lighting** shows only images with both.
- **Excluding tags** — click a tag twice to exclude it. Excluded tags are shown in red.

The filter panel's left column shows categories with coloured dot indicators. Active categories show a count badge. The right column shows pill-style options for the selected category, with a search bar for large categories.

## Managing Tags

From **Settings > Tag Categories**, you can:

- Create custom categories with a colour and icon
- Add, rename, or delete tag values within a category
- Define aliases for tag values
- Set display order for categories
- Import or remove tag packs
