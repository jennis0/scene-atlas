# What is Scene Atlas?

Scene Atlas is a self-hosted scene manager for tabletop RPG art. It lets you import large collections of battlemaps, encounter art and vistas, then search them by visual content rather than filename.

<!-- TODO: screenshot — gallery dark mode overview -->

## The Problem

If you run tabletop RPGs, you probably have hundreds (or thousands) of scene images in nested folders. Finding the right map mid-session means scrolling through directories, guessing at filenames, or settling for whatever's close enough.

## How Scene Atlas Helps

**Import your collection.** Drag and drop files, folders, or ZIPs into the web UI. During import, Scene Atlas extracts metadata from filenames, detects grid patterns on battlemaps, pulls out dominant colours, and generates embeddings that capture what each image looks like.

**Search by description.** Type "a dark cave with glowing mushrooms" and get results that match visually, regardless of what the files are called. The search combines keyword matching, visual similarity, and tag alias expansion, then merges the ranked results so the best matches surface first.

**Browse by concept.** Related map variants (snowy, fey, summer, gridded, gridless) are automatically grouped during import. The gallery shows groups as hero + mosaic cards so you can scan by scene rather than scrolling individual files.

## Key Capabilities

- **Visual search** using AI embeddings that understand image content
- **Hybrid search** combining keywords, visual similarity, and tag aliases
- **Auto-grouping** of related variants by folder structure and naming patterns
- **Customisable tags** with genre-specific starter packs (Fantasy, Sci-Fi, Horror, Cyberpunk, Historical), custom categories, and alias-powered search expansion
- **Grid detection** for square and hex grids on battlemaps
- **Colour search** by dominant colour (5 per image)
- **Multiple AI model sizes** from CPU-friendly to high-accuracy
- **Video support** for MP4 and WebM files (first frame extracted for search)
- **Type-aware processing** where battlemaps get grid analysis and scenes skip it

## Scope

Scene Atlas organises art you already have. It is not a virtual tabletop, a map editor, or a cloud service. Everything runs locally on your hardware.

## Supported Platforms

| Platform | Desktop App | Server (Docker) | Server (Standalone) |
|----------|:-----------:|:---------------:|:-------------------:|
| Windows  | NSIS installer | Docker Desktop | Manual |
| macOS    | DMG (Apple Silicon only) | Docker Desktop | Manual |
| Linux    | AppImage + DEB | Native Docker | Manual |

## Next Steps

Head to the [Installation guide](/guide/getting-started) to get running.
