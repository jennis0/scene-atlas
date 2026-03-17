# What is Scene Atlas?

Scene Atlas is a self-hosted, AI-powered scene manager for tabletop RPG art. It helps you search, organise, and browse large collections of battlemaps, encounter art, portraits, and vistas — using the actual visual content, not just filenames.

<!-- TODO: screenshot — gallery dark mode overview -->

## The Problem

If you run tabletop RPGs, you probably have hundreds or thousands of scene images scattered across folders. Finding the right map for tonight's session means scrolling through directories, relying on filenames you can barely remember, or giving up and using the first vaguely-relevant result.

## How Scene Atlas Helps

**Import your collection** — drag and drop images or folders. Scene Atlas analyses each image: extracting tags from filenames, detecting grid patterns, identifying dominant colours, and generating AI embeddings that understand visual content.

**Search by description** — type "a dark cave with glowing mushrooms" and find maps that look like that, even if the filename is `cave_final_v3.jpg`. Hybrid search combines keyword matching, AI visual understanding, and tag aliases for the best results.

**Browse by concept** — related map variants (snowy, fey, summer versions of the same scene) are automatically grouped. A hero + mosaic gallery lets you browse by scene rather than by individual file.

## Key Capabilities

- **Semantic search** — CLIP/SigLIP2 AI models understand image content visually
- **Hybrid search** — combines full-text, semantic, and tag alias matching via Reciprocal Rank Fusion
- **Auto-grouping** — detects related variants from folder structure and naming patterns
- **Tag system** — genre-specific packs (Fantasy, Sci-Fi, Horror, and more) with alias-powered search
- **Grid detection** — automatic square and hex grid detection for battlemaps
- **Colour search** — find scenes by dominant colour (5 colours extracted per image)
- **Multiple AI models** — small (CPU-friendly), medium, and large (GPU recommended)
- **Type-aware** — battlemaps get grid detection; scenes skip it

## What Scene Atlas is Not

- **Not a virtual tabletop (VTT)** — it helps you find maps, not run sessions
- **Not a cloud service** — everything runs on your hardware, your images never leave your machine
- **Not a map maker** — it organises art you already have

## Supported Platforms

| Platform | Desktop App | Server (Docker) | Server (Standalone) |
|----------|:-----------:|:---------------:|:-------------------:|
| Windows  | NSIS installer | Docker Desktop | Manual |
| macOS    | DMG (Intel + Apple Silicon) | Docker Desktop | Manual |
| Linux    | AppImage + DEB | Native Docker | Manual |

## Next Steps

Ready to try it? Head to the [Installation guide](/guide/getting-started) to get started in under five minutes.
