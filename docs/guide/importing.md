# Importing Scenes

Import happens through the web UI. Drag and drop files, folders, or ZIP archives; Scene Atlas groups them, uploads them, and processes them in the background.

## Supported Formats

| Type | Formats |
|------|---------|
| Images | JPG, PNG, WebP |
| Video | MP4, WebM (first frame extracted for search) |
| Archives | ZIP (unpacked automatically on the server) |

## The Import Flow

### 1. Choose your files

Click **Import** in the top bar. Choose **Battlemaps** (grids are detected automatically) or **Scenes** (vistas, portraits and encounter art, no grid detection), then drop files, folders or ZIP archives onto the dialog, or use **Choose a folder** / **Choose files**. The type applies to every file in that import; you can change an image's type afterwards in the group editor.

<!-- TODO: screenshot — import dialog start view -->

### 2. Grouping and upload

The browser first sends the list of files and their folder paths, then any ZIP archives (unpacked on the server). The server sorts the files into groups and parses metadata before any image bytes are uploaded:

- **Auto-grouping** uses folder structure first, then shared filename prefixes (e.g., `ForestClearing_Summer.jpg` and `ForestClearing_Winter.jpg` end up together). A group whose name and author match an existing one is added to it.
- **Metadata extraction** parses author names, grid dimensions and tags from filenames and folders where possible.

The import refuses to start if there is not enough free disk space for it. There is no review step: files start uploading and processing immediately. You can rename groups, move images between them or change their type afterwards (see [Groups](/guide/groups)).

### 3. Processing

Files are uploaded by a small pool of parallel uploads. Each file is hashed in the browser first, and files whose exact bytes are already in the library are not uploaded. Each file is processed as soon as it arrives, in small batches, so processing overlaps the upload:

1. **Duplicate check** on the decoded pixels (catches the same image saved differently)
2. **Thumbnail generation** for fast gallery rendering
3. **Colour extraction** (5 dominant colours per image)
4. **Grid detection** for battlemaps only (square and hex)
5. **AI embedding** for semantic search
6. **Full-text indexing** of name, filename, author, and tags

The dialog shows how many files have been received and processed, and a list of groups with their progress. Images appear in the gallery as they finish. Every file is saved on its own: if one file fails, everything else is kept.

You can **Pause**, **Resume** or **Cancel** an import. Cancelling stops the remaining files but keeps everything already imported.

### The Activity Dock

You can close the import dialog at any time. The **Activity Dock** in the bottom-right lists every import with its progress; click one to reopen it. When an import finishes you get a notification with a link to its report. **Dismiss** hides a finished import from the list; it never deletes anything.

If Scene Atlas can't carry on for a reason outside your files (the disk is full, the image library folder is unreachable, or the AI model is loading or changing), imports pause with an explanation and continue by themselves once the problem clears. **Try again now** checks straight away. Work in progress also resumes when the backend restarts.

### Interrupted uploads

Files are sent from your browser, so closing the tab or losing your connection stops the upload (processing of files already received carries on). If the connection drops briefly, the upload waits and resumes on its own.

If the upload was interrupted, the import shows **Upload interrupted**. Choose the same folder or files again to send just the missing ones, or **Finish without them** to complete the import with what arrived.

## The Import Report

Open the report from the finished import or its notification. It has up to four sections:

- **Groups**: every group the import created or added to. Click one to open it in the editor, or use **Review in editor** to go through them all.
- **Problems**: files that couldn't be imported, grouped by reason. **Retry** tries them again.
- **Already in library**: duplicates that were skipped (see below).
- **Skipped**: files that weren't imported, such as unsupported file types or files never uploaded.

### Duplicates

Scene Atlas skips a file automatically only when it is certainly already in your library:

- **Identical file**: the exact same bytes. Where possible this is checked before uploading, so the file is never sent.
- **Same picture**: the same image saved differently, for example a PNG re-saved with different compression or edited metadata.

Variants that only look similar (gridded vs gridless, night vs day) are never skipped. If a match is wrong, or you want a separate copy, choose **Import as new copies** in the *Already in library* section.

### Undo import

**Undo import** in the report deletes every image that import added, then removes the import itself. You are asked to confirm first, with a count of what will be deleted.

## Limits

These defaults can be changed in **Settings** (see the [Configuration Reference](/deploy/configuration#runtime-settings)):

| Limit | Default | Applies to |
|-------|---------|------------|
| Max file size | 2 GB | Each file |
| Max video file size | 2 GB | Each video |
| Max files per zip | 1,000 | Files inside one ZIP archive |
| Max zip size (uncompressed) | 2 GB | Unpacked contents of one ZIP archive |

An import can contain up to 50,000 files (server setting `MAX_IMPORT_ITEMS`).

## Stored Format

By default Scene Atlas keeps every image exactly as you uploaded it, under content-addressed names in the image library. **Settings → Stored format** can instead store new imports as:

- **WebP**: the smallest files. PNGs are converted losslessly (pixel-perfect) unless you turn off *Lossless WebP for PNGs*; JPEGs always use the quality setting, because lossless WebP would make them larger.
- **JPEG**: small files. Images with transparency stay as uploaded.
- **PNG**: lossless, but usually larger than the original.

*Quality* (default 90) applies to WebP and JPEG. Files already in the chosen format, animated images and very large images (over 16,383 px for WebP) are kept as uploaded. The setting only affects new imports, and duplicate detection works the same whichever format you pick. Original filenames are preserved in the database regardless.

## Tips

- **Large collections:** A whole library folder can go in one import (up to 50,000 files). Keep the tab open until the upload finishes; processing continues without it. Several imports run side by side and share processing fairly, so a small drop never waits behind a large one.
- **Naming conventions:** The auto-grouper works best when related files share a prefix (e.g., `TavernBrawl_Grid.jpg`, `TavernBrawl_Gridless.jpg`, `TavernBrawl_Night.jpg`).
- **Folder structure:** If your files are already organised into folders per scene, Scene Atlas detects that structure as groups.
- **Duplicates:** Re-importing a file that already exists skips it automatically, usually without even uploading it. Near-identical variants (gridded/gridless, lighting) are not treated as duplicates.
