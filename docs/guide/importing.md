# Importing Scenes

Scene Atlas processes your images in the browser — drag and drop files, folders, or ZIP archives and let the pipeline handle the rest.

## Supported Formats

| Type | Formats |
|------|---------|
| Images | JPG, PNG, WebP |
| Video | MP4, WebM (first frame extracted for search) |
| Archives | ZIP (automatically extracted during upload) |

## The Import Flow

### 1. Upload

Click **Import** in the top bar, then drag files into the upload area or use the file picker. You can upload individual files, entire folders, or ZIP archives.

Files are uploaded in batches to prevent timeouts on large imports. A progress bar tracks the upload.

<!-- TODO: screenshot — import dialog upload step -->

### 2. Analysis

After upload completes, Scene Atlas analyses your files:

- **Duplicate detection** — files are checked against your existing library by SHA-256 hash. Duplicates are flagged and skipped.
- **Auto-grouping** — a two-pass algorithm groups related files: first by folder structure, then by filename prefix patterns (e.g., `ForestClearing_Summer.jpg` and `ForestClearing_Winter.jpg` are grouped together).
- **Metadata extraction** — author names, grid dimensions, and descriptive tags are parsed from filenames where possible.

### 3. Review and Confirm

The analysis results show your detected groups. You can:

- Rename groups or change the author
- Move images between groups
- Merge groups together
- Set image type per file (battlemap or scene)

::: tip
**Battlemaps** get grid detection applied automatically. **Scenes** (vistas, portraits, encounter art) skip grid detection. Choose the right type for best results.
:::

### 4. Processing

Once confirmed, images are processed in batches:

1. **Thumbnail generation** — preview images for fast gallery rendering
2. **Colour extraction** — 5 dominant colours identified via K-means clustering
3. **Grid detection** — for battlemaps only; detects square and hex grids from the image
4. **AI embedding** — CLIP/SigLIP2 model generates a vector embedding for semantic search
5. **Full-text indexing** — name, filename, author, and tags indexed for keyword search

The **Activity Dock** in the bottom-right corner shows progress for all running imports. You can close the import dialog and continue browsing while processing runs in the background.

## Limits

These defaults can be changed in [Settings](/deploy/configuration):

| Limit | Default |
|-------|---------|
| Max file size | 2 GB |
| Max video file size | 2 GB |
| Max files per import | 1,000 |
| Max total import size | 2 GB |

## WebP Conversion

By default, imported images are converted to WebP format for storage efficiency. This is lossless at quality 95 and can be disabled in Settings. Original filenames are preserved in the database regardless.

## Tips

- **Large collections:** Import in batches of a few hundred at a time for smoother progress tracking
- **Naming conventions:** The auto-grouper works best when related files share a prefix (e.g., `TavernBrawl_Grid.jpg`, `TavernBrawl_Gridless.jpg`, `TavernBrawl_Night.jpg`)
- **Folder structure:** If your files are already organised into folders per scene, Scene Atlas will detect that structure as groups
- **Duplicates:** If you re-import a file that already exists, the duplicate is skipped and the existing embedding is reused — no wasted processing time
