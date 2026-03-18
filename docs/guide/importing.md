# Importing Scenes

Import happens through the web UI. Drag and drop files, folders, or ZIP archives and follow the steps below.

## Supported Formats

| Type | Formats |
|------|---------|
| Images | JPG, PNG, WebP |
| Video | MP4, WebM (first frame extracted for search) |
| Archives | ZIP (extracted automatically during upload) |

## The Import Flow

### 1. Upload

Click **Import** in the top bar, then drag files into the upload area or use the file picker. Files are uploaded in batches with a progress bar.

<!-- TODO: screenshot — import dialog upload step -->

### 2. Analysis

After upload, Scene Atlas analyses your files:

- **Duplicate detection** checks against your existing library by SHA-256 hash. Duplicates are flagged and skipped.
- **Auto-grouping** runs a two-pass algorithm: first by folder structure, then by filename prefix patterns (e.g., `ForestClearing_Summer.jpg` and `ForestClearing_Winter.jpg` are grouped together).
- **Metadata extraction** parses author names, grid dimensions, and tags from filenames where possible.

### 3. Review and Confirm

The analysis results show your detected groups. You can:

- Rename groups or change the author
- Drag images between groups to reorganise them
- Merge groups together
- Set image type per file (battlemap or scene)

::: tip
**Battlemaps** get grid detection applied automatically. **Scenes** (vistas, encounter art) skip grid detection. Choose the right type for best results.
:::

### 4. Processing

Once confirmed, images are processed in batches:

1. **Thumbnail generation** for fast gallery rendering
2. **Colour extraction** (5 dominant colours per image)
3. **Grid detection** for battlemaps only (square and hex)
4. **AI embedding** for semantic search
5. **Full-text indexing** of name, filename, author, and tags

The **Activity Dock** in the bottom-right shows progress for all running imports. You can close the import dialog and continue browsing while processing runs in the background.

## Limits

These defaults can be changed in [Settings](/deploy/configuration):

| Limit | Default |
|-------|---------|
| Max file size | 2 GB |
| Max video file size | 2 GB |
| Max files per import | 1,000 |
| Max total import size | 2 GB |

## WebP Conversion

By default, imported images are converted to WebP for storage efficiency. Two modes are available in Settings:

- **Lossless** (default): exact pixel-for-pixel copy in a smaller file
- **Lossy**: configurable quality level (default 95) for further size reduction

Original filenames are preserved in the database regardless of conversion.

## Tips

- **Large collections:** Import in batches of a few hundred for smoother progress tracking.
- **Naming conventions:** The auto-grouper works best when related files share a prefix (e.g., `TavernBrawl_Grid.jpg`, `TavernBrawl_Gridless.jpg`, `TavernBrawl_Night.jpg`).
- **Folder structure:** If your files are already organised into folders per scene, Scene Atlas detects that structure as groups.
- **Duplicates:** Re-importing a file that already exists skips it automatically. No wasted processing.
