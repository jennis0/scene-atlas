# Importing Scenes

Import happens through the web UI. Drag and drop files, folders, or ZIP archives; Scene Atlas groups them, uploads them, and processes them in the background.

## Supported Formats

| Type | Formats |
|------|---------|
| Images | JPG, PNG, WebP |
| Video | MP4, WebM (first frame extracted for search) |
| Archives | ZIP (extracted automatically during upload) |

## The Import Flow

### 1. Choose files

Click **Import**, choose whether the files are **Battlemaps** or **Scenes**, then drop files, folders, or ZIP archives onto the dialog, or use **Choose a folder** / **Choose files**. The type applies to every file in that import.

::: tip
**Battlemaps** get grid detection. **Scenes** (vistas, encounter art) skip it. Choose the right type for best results; you can change an image's type afterwards in the group editor.
:::

<!-- TODO: screenshot — import dialog start view -->

### 2. Grouping

The browser first sends the list of files and their folder paths, then any ZIP archives (expanded on the server). The server then groups the files and parses metadata before any image bytes are uploaded:

- **Auto-grouping** uses folder structure first, then shared filename prefixes (e.g., `ForestClearing_Summer.jpg` and `ForestClearing_Winter.jpg` are grouped together).
- **Metadata extraction** parses author names, grid dimensions, and tags from filenames and folders where possible.

The import refuses to start if there is not enough free disk space for it.

### 3. Upload and processing

Files are then uploaded one at a time by a small pool of parallel uploads. Each file is hashed in the browser first, and files whose exact bytes are already in the library are skipped without being uploaded. Processing starts as soon as files arrive, so it overlaps the upload:

1. **Duplicate check** on the decoded pixels (catches the same image saved differently)
2. **Thumbnail generation** for fast gallery rendering
3. **Colour extraction** (5 dominant colours per image)
4. **Grid detection** for battlemaps only (square and hex)
5. **AI embedding** for semantic search
6. **Full-text indexing** of name, filename, author, and tags

Each file is saved on its own, so finished images appear in the gallery while the rest of the import continues. The dialog shows upload progress and a ledger of groups as they fill in.

### Running imports

- **Close the dialog at any time.** The import keeps running, and the **activity dock** shows progress for all imports. Reopening the import shows the same job.
- **Pause or resume** from the dialog or the dock, and **cancel** from the dialog. Cancelling keeps the images that already finished.
- **Interrupted uploads** (closed tab, lost connection) can be resumed by choosing the same folder or files again; only the missing files are sent. A lost connection pauses uploading until it returns.
- **Restarts are safe.** Work in progress resumes when the backend starts again. Problems such as a full disk or a model change pause the queue and show the reason, rather than failing files.

### Import report

When an import finishes, open its report to see:

- **Groups** created, with links into the group editor
- **Problems**, grouped by reason, with **Try again**
- **Files already in the library**, with **Import as new copy** for a file that was wrongly matched as a duplicate
- **Skipped** files (for example unsupported formats)

From the report you can also **Undo import** (deletes the images it created, after confirmation) or dismiss it.

## Limits

These defaults can be changed in **Settings** (see the [Configuration Reference](/deploy/configuration#runtime-settings)):

| Limit | Default | Applies to |
|-------|---------|------------|
| Max file size | 2 GB | Each file |
| Max video file size | 2 GB | Each video |
| Max files per import | 1,000 | Files inside one ZIP archive |
| Max total upload size | 2 GB | Uncompressed contents of one ZIP archive |

A single import can contain up to 50,000 files (server setting `MAX_IMPORT_ITEMS`).

## Storage

Imported files are stored as uploaded, under content-addressed names in the image library. Original filenames are kept in the database. The **Convert to WebP** setting is currently not applied by the import pipeline.

## Tips

- **Large collections:** A whole library folder can go in one import (up to 50,000 files). Keep the tab open until the upload finishes; processing continues without it.
- **Naming conventions:** The auto-grouper works best when related files share a prefix (e.g., `TavernBrawl_Grid.jpg`, `TavernBrawl_Gridless.jpg`, `TavernBrawl_Night.jpg`).
- **Folder structure:** If your files are already organised into folders per scene, Scene Atlas detects that structure as groups.
- **Duplicates:** Files whose bytes or decoded pixels match an existing image are skipped automatically. Near-identical variants (gridded/gridless, lighting) are not treated as duplicates.
