# Importing

Click **Import** in the top bar, choose what the images are, then drop files, folders or ZIP archives onto the dialog, or use **Choose a folder** / **Choose files**. The import starts straight away and runs in the background.

Importing copies images into Scene Atlas. To use a folder of images where it is, without copying, see [Your own folder](/guide/library#importing-vs-using-your-own-folder).

## Supported Files

| Type | Formats |
|------|---------|
| Images | JPG, PNG, WebP |
| Video | MP4, WebM (searched by their first frame) |
| Archives | ZIP, unpacked on import |

Other files are skipped and listed in the import report.

## Image Types

**Import these as** sets how each image is handled:

| Choice | What happens |
|--------|--------------|
| **Auto** (default) | Each image is sorted into battlemaps or scenes. Tokens and other art are skipped for you to check. |
| **Battlemaps** | Top-down maps. Grids are detected. |
| **Scenes** | Vistas, portraits and encounter art. No grid detection. |

The choice applies to the whole import. You can change an image's type afterwards in the viewer or the group editor.

### Images Auto skipped

Auto skips images that look like tokens or aren't maps or scenes, and anything it can't decide on. They are listed under **Skipped** in the import report with the reason, and in the group editor for the group they would have joined. **Include** imports them after all.

Skipped images can be included until you clear the import from Activity (the report's **Done** does this) or for 24 hours after the import finishes, whichever comes first.

## Groups and Names

Scene Atlas sorts files into [groups](/guide/groups) as the import starts:

- **Folders** are read as `Author/Group/Subgroup/file`. `Czepeku/Forest Clearing/summer.jpg` and `Czepeku/Forest Clearing/winter.jpg` become one group, *Forest Clearing* by Czepeku. Deeper folders become [subgroups](/guide/groups#subgroups), and generic folders such as `Gridded` or `VTT` are skipped.
- **Shared filename prefixes** group loose files. `TavernBrawl_Grid.jpg` and `TavernBrawl_Night.jpg` end up together.
- **Authors** can also come from a filename, such as `ArenabyUpsetti.jpg`.
- **Grid sizes and tags** are read from folder and file names where possible.
- A group whose name and author match an existing one is added to it.

There's no review step before the import starts. Fix anything afterwards with **Review in editor** in the report, or in the [group editor](/guide/groups#editing-groups).

## Following an Import

The import dialog shows how many files are done, a list of groups with their progress, and roughly how long is left. Images appear in the gallery as they finish.

- **Pause** / **Resume** stop and restart processing.
- **Cancel import** stops it. Everything already imported is kept.
- **Close** hides the dialog. The import carries on.

The **Activity** list in the bottom-right corner shows every import. Click one to reopen it. Several imports can run at once and share processing fairly, so a small import isn't stuck behind a big one.

If Scene Atlas can't carry on for a reason outside your files, such as a full disk, an unreachable image folder or a search model that is loading or changing, imports pause with an explanation and continue once the problem clears. **Try again now** checks straight away. Imports also carry on after a restart.

### Desktop app: imports read your files directly

In the desktop app, files and folders you choose or drop are read straight from your disk. Nothing is uploaded, closing the import dialog or the app doesn't stop it, and an import can hold up to 250,000 files.

If the drive or share you imported from is disconnected, the import waits ("Waiting for D:\Maps") and carries on when it's back.

### Browser: imports upload your files

In a browser, files are uploaded to the server. An import can hold up to 50,000 files.

- Files already in the library are recognised before they are uploaded and skipped.
- Keep the tab open until the upload finishes. Processing carries on without it.
- If your connection drops briefly, the upload resumes on its own.

If the tab was closed or the connection was lost, the import shows **Upload interrupted**. Choose the same folder or files again to send only the missing ones, or **Finish without them**.

## The Import Report

Open the report from the import's notification or from Activity. It has up to four sections:

- **Groups**: every group the import created or added to. Click one to open it, or **Review in editor** to go through them all.
- **Problems**: files that couldn't be imported, by reason. **Retry** tries them again.
- **Already in library**: duplicates that were skipped.
- **Skipped**: unsupported files, files never uploaded, and images [Auto skipped](#images-auto-skipped).

**Undo import** deletes every image the import added, after asking you to confirm.

### Duplicates

A file is skipped only when it is certainly already in your library:

- **Identical**: the exact same file.
- **Same picture**: the same image saved differently, for example re-saved with different compression.

Variants that only look alike, such as gridded and gridless or day and night, are always imported. If a match is wrong, or you want a second copy, choose **Import as new copies** under *Already in library*.

## Stored Format

By default each image is kept exactly as imported. **Settings → Import Limits → Stored format** can store new imports as:

- **WebP**: the smallest files. PNGs are converted losslessly unless you turn off *Lossless WebP for PNGs*.
- **JPEG**: small files. Images with transparency stay as they are.
- **PNG**: lossless, but usually larger than the original.

*Quality* (default 90) applies to WebP and JPEG. Files already in that format, animations and very large images stay as they are. The setting affects new imports only, and doesn't apply to [your own folder](/guide/library#using-your-own-folder), which is never changed.

## Limits

| Limit | Default | Set in |
|-------|---------|--------|
| File size | 2 GB | Settings → Import Limits |
| Video size | 2 GB | Settings → Import Limits |
| Files in one ZIP | 1,000 | Settings → Import Limits |
| Unpacked size of one ZIP | 2 GB | Settings → Import Limits |
| Files in one import | 50,000 uploaded, 250,000 in the desktop app | `MAX_IMPORT_ITEMS`, `MAX_LOCAL_IMPORT_ITEMS` ([Configuration](/deploy/configuration#import)) |

An import won't start if there isn't enough free disk space for it.

## Tips

- **Organise by folder first.** `Author/Scene/files` gives the cleanest groups and fills in authors for you.
- **Import a whole collection at once.** Scene Atlas handles tens of thousands of files in one import. Processing a large collection takes hours, mostly spent on the search model.
- **Re-importing is safe.** Files already in the library are skipped.
