# How Search Works

The detail behind [Searching](/guide/searching), for anyone tuning results or curious about why an image ranks where it does.

## Three Searches, One List

A query with no prefix runs three searches at once:

1. **Keyword** (SQLite FTS5) matches the words against image names, filenames, authors and tags. Words are stemmed ("running" matches "run") and accents are ignored. `AND`, `OR` and `NOT` are treated as ordinary words and dropped.
2. **Visual** turns the query into an embedding with the active [search model](/deploy/configuration#model-details) and compares it with every image's embedding.
3. **Alias** looks up [tag aliases](/guide/tags#aliases) for the query's words ("rainy" → "rain") and runs them as a second keyword search.

The three ranked lists are merged with Reciprocal Rank Fusion (RRF). Each image scores `weight / (k + rank)` for every list it appears in, with k = 60 and weights of 1.1 for keyword, 1.0 for visual and 0.5 for alias, so synonyms never outrank the words you typed. The scores are summed. An image that ranks well in several lists rises to the top without any one search dominating.

`~` runs only the visual search and `=` only the keyword search. A quoted phrase is matched as adjacent words and isn't expanded with aliases.

The **Relevance** slider filters on the summed RRF score in the browser; it doesn't re-run the search.

## Colour Matching

At import, each image's pixels are sampled and clustered (k-means) into 5 dominant colours, stored in the CIELAB colour space.

A colour filter matches an image when any of its dominant colours is within a CIE76 delta E of the chosen colour. Delta E is the straight-line distance in LAB: about 2 is barely noticeable, about 10 is clearly a similar shade.

| Settings → Colour match | Delta E |
|-------------------------|---------|
| Close | 12 |
| Similar (default) | 25 |
| Broad | 40 |

Any value from 0 to 100 can be set with `color_distance_threshold` through the [settings API](/deploy/configuration#runtime-settings). The number of colours and the clustering are set there too.

## Search Models

Larger models understand descriptions better but make importing slower, and changing model re-processes every image. See [Model Details](/deploy/configuration#model-details).
