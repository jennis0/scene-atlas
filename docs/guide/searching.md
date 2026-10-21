# Searching

Type what you're looking for in the search box at the top of the gallery. Press `/` to jump to it from anywhere in the gallery.

Scene Atlas matches your words against names, authors, filenames and tags, and against what the images actually look like, then puts the best matches from both first. "A dark cave with glowing mushrooms" finds caves with glowing mushrooms whatever the files are called.

## Search Syntax

| Query | What it does | Use it for |
|-------|--------------|------------|
| `forest clearing` | Words and visual match together | Most searches |
| `~underwater temple` | Visual match only | Describing a scene you can picture |
| `=Czepeku` | Words only | Names, authors and filenames you know |
| `"dark forest"` | The exact phrase | Multi-word names |

Words match their variants: "forests" finds "forest". Searches also include each tag's [aliases](/guide/tags#aliases), so "rainy" finds images tagged "rain". Quoted phrases aren't expanded with aliases.

## Results

With a search, results are sorted by **Relevance**. The **Relevance** slider in the results bar hides weaker matches; drag it right if a search returns too many loosely related images. It isn't shown for `=` searches.

The address of the page holds the search and filters, so you can bookmark a search or share its link with someone using the same server.

## Filters

Open **Filters** next to the search box. Filters narrow the results with or without a search.

| Filter | Options |
|--------|---------|
| **Each tag category** | That category's tags, such as Lighting or Environment |
| **Author** | Every author in the library |
| **Grid** | Square grid, Hex grid, Any gridded, Gridless, Unknown |
| **Media** | Images or Videos |
| **Color** | A palette of common colours, or any colour you pick |

Click an option to include it. **Right-click it to exclude it** instead; excluded filters show in red. Active filters appear as chips under the search box, where you can remove them one at a time or all at once. With a lot of tags, use **Search filters…** at the top of the menu to find one.

How filters combine:

- Options in the **same tag category** are combined with OR: *forest* and *cave* shows images with either.
- **Different categories** and different filters are combined with AND: *forest* and *night* shows only images with both.
- **Colours** are combined with OR.

The **All / Maps / Scenes** tabs above the gallery limit everything, including search, to one image type.

## Colour Search

Each image has its 5 main colours picked out when it's imported. A colour filter matches images where any of those is close to the colour you chose. How close is set by **Settings → General → Colour match**: *Close*, *Similar* (the default) or *Broad*.

## Tips

- **Describe the scene.** "A sunlit tavern with wooden beams and a roaring fireplace" works better than "tavern".
- **Prefix `=` for exact names.** It skips visual matching, so an author's name doesn't pull in look-alikes.
- **Search, then filter.** Search for "cave", then filter to gridded maps.
- **Larger search models find more.** See [Settings → Search Model](/guide/settings#search-model).

For how results are ranked, see [How Search Works](/reference/search).
