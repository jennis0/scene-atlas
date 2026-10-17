# Searching

Scene Atlas runs three search strategies on every query and merges the results. You just type what you're looking for.

## Search Modes

| Mode | Prefix | What it does | Best for |
|------|--------|-------------|----------|
| **Hybrid** | *(none)* | Combines keyword, visual, and alias matching | Most searches |
| **Semantic only** | `~` | Matches by visual similarity only | Describing a scene you can picture |
| **Text only** | `=` | Exact keyword matching | Known filenames or author names |

### Examples

| Query | Mode | What happens |
|-------|------|-------------|
| `forest clearing` | Hybrid | Keywords match filenames/tags, visual search finds similar-looking images, aliases expand matches |
| `~underwater temple` | Semantic | Finds images that look like underwater temples, regardless of filename |
| `=Czepeku` | Text | Exact match on the author name "Czepeku" |
| `"dark forest"` | Hybrid (phrase) | Quoted phrase matched as adjacent words, not expanded by aliases |

## How Hybrid Search Works

When you type a query without a prefix, three searches run in parallel:

1. **Full-text search** matches keywords against image names, filenames, authors, and tags. Word stemming is applied ("forests" matches "forest", "running" matches "run").

2. **Semantic search** converts your query into an AI embedding and compares it to every image's embedding. This finds visually relevant results even when no keywords match.

3. **Alias expansion** looks up tag aliases (e.g., "rainy" also searches for "rain") and runs them as a separate text search.

Results from all three are merged by rank. An image that scores well in multiple strategies gets boosted to the top. See the [Configuration Reference](/deploy/configuration) for technical details on the ranking algorithm.

## Filters

Filters narrow results independently of the search query. Open the filter panel from the gallery header.

| Filter | Behaviour |
|--------|-----------|
| **Image type** | Battlemap or Scene |
| **Media type** | Image or Video |
| **Grid state** | Gridded, Gridless, or Unknown |
| **Grid type** | Square or Hex |
| **Authors** | Include or exclude specific authors |
| **Tags** | OR within a category, AND across categories |
| **Colours** | Match against dominant colours extracted from images |

::: tip
Tag filters follow intuitive logic: selecting "forest" and "cave" within the **environment** category shows images tagged with *either*. But selecting "forest" in **environment** and "night" in **lighting** shows only images with *both*.
:::

## Colour Search

Each image has 5 dominant colours extracted during import. Colour filtering uses perceptual distance (CIE76 delta E in the LAB colour space), so "close enough" colours match rather than requiring exact hex values. An image matches when any of its dominant colours is within the colour distance threshold (default 25) of a selected colour. Lower it with `PATCH /api/v1/settings` (`color_distance_threshold`) for stricter matches: around 10 is a clearly similar shade, around 2 is barely distinguishable.

## Tips

- **Be descriptive for semantic search:** "a sunlit tavern with wooden beams and a roaring fireplace" works better than just "tavern".
- **Use text mode for exact matches:** Prefix with `=` when you know the exact name or author.
- **Combine search with filters:** Search for "cave" then filter to "gridded battlemaps" to narrow results.
- **Quoted phrases:** Wrap multi-word phrases in quotes for exact adjacent-word matching.
- **Tag aliases work automatically:** Searching for "rainy" includes images tagged "rain" with no extra effort.
