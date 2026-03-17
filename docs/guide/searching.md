# Searching

Scene Atlas combines three search strategies into a single query. Type what you're looking for and the system figures out the best way to find it.

## Search Modes

| Mode | Prefix | How it works | Best for |
|------|--------|-------------|----------|
| **Hybrid** | *(none)* | Combines keyword, semantic, and alias matching | Most searches |
| **Semantic only** | `~` | AI visual understanding only | Describing a scene visually |
| **Text only** | `=` | Exact keyword matching (FTS5) | Known filenames or author names |

### Examples

| Query | Mode | What happens |
|-------|------|-------------|
| `forest clearing` | Hybrid | Keywords match filenames/tags, AI finds visually similar images, aliases expand matches |
| `~underwater temple` | Semantic | AI finds images that look like underwater temples, regardless of filename |
| `=Czepeku` | Text | Exact match on author name "Czepeku" |
| `"dark forest"` | Hybrid (phrase) | Quoted phrase matched as adjacent words; not expanded by aliases |

## How Hybrid Search Works

When you type a query without a prefix, three independent searches run:

1. **Full-text search** — keyword matching with Porter stemming against image names, filenames, authors, and search text. "forests" matches "forest", "running" matches "run".

2. **Semantic search** — your query is converted to an AI embedding (using the same CLIP/SigLIP2 model used to index images) and compared to every image's embedding. This finds visually similar results even when no keywords match.

3. **Alias expansion** — tag aliases are looked up (e.g., "rainy" expands to also search for "rain") and run as a separate text search.

Results from all three are merged using **Reciprocal Rank Fusion (RRF)** — a technique that combines ranked lists fairly, so a result that ranks highly in multiple strategies is boosted to the top.

## Filters

Filters narrow your results independently of the search query. Available in the filter panel on the left side of the gallery.

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
Tag filters follow an intuitive logic: selecting "forest" AND "cave" within the **environment** category matches images tagged with *either* forest or cave. But selecting "forest" in **environment** and "night" in **lighting** matches images with *both*.
:::

## Colour Search

Each image has 5 dominant colours extracted during import. You can filter by colour from the gallery filter panel — Scene Atlas uses LAB colour distance to find perceptually similar matches, not exact hex values.

## Tips for Better Results

- **Be descriptive for semantic search:** "a sunlit tavern with wooden beams and a roaring fireplace" works better than "tavern"
- **Use text mode for exact matches:** Prefix with `=` when you know the exact name or author
- **Combine search with filters:** Search for "cave" then filter to "gridded battlemaps" to narrow results
- **Quoted phrases:** Wrap multi-word phrases in quotes for exact adjacent-word matching
- **Tag aliases help automatically:** If you search for "rainy", images tagged "rain" are included without you needing to think about it
