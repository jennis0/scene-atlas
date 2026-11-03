# Your Library

A Scene Atlas library is stored in up to three folders:

| Place | Holds | Desktop default | Server setting |
|-------|-------|-----------------|----------------|
| **Search data** | Database, thumbnails, search index, AI models, logs | `%LOCALAPPDATA%\Scene Atlas\data` (Windows), `Documents/Scene Atlas/data` (macOS, Linux) | `SCENE_ATLAS_DATA_DIR` |
| **Imported images** | Full-size copies of images you import | `…\Scene Atlas\images`, or `<linked library>\Scene Atlas` when you link one | `SCENE_ATLAS_IMAGES_DIR` |
| **Linked library** (optional) | A folder of images you already have, read where they are | none | `SCENE_ATLAS_LINKED_LIBRARY_DIR` |

Search data is best on a fast drive. Imported images can go on any large drive.

## Importing vs linking

There are two ways to get images in, and you can use both:

- **Import** copies images into *Imported images*. The originals are left alone and can be deleted afterwards. See [Importing](/guide/importing).
- **Linking** reads a library you already keep where it is. Nothing is copied, and Scene Atlas never changes, moves or deletes anything in it. Images you add to it later are picked up on their own.

Link a library when you already keep a well-organised collection and don't want a second copy of it. Import when your images are scattered across downloads, or when you want Scene Atlas to hold its own copy.

Scene Atlas's own files have generated names and no folder structure. Don't edit, rename or move anything inside *Search data* or *Imported images*.

## Linked library

**Desktop app:** choose *Link a library you already have* in the setup's library step, or set *Linked library* later in **Settings → Storage locations**.

![The setup's library step with Link a library you already have chosen: the folder, how many images it holds, and where Imported images and Search data will go](/screenshots/setup-library.webp)

**Server:** set `SCENE_ATLAS_LINKED_LIBRARY_DIR` and mount the folder read-only. See [Docker Server: Linked library](/deploy/server#linked-library).

You can link one library. Its first scan adds every map and scene in it, using [Auto](/guide/importing#image-types) to sort them and to skip tokens and other art. A large folder takes a few hours; the gallery fills as images are added. Folder names become authors and groups in the same way as an import.

### Keeping up with changes

Scene Atlas checks the folder for changes when it starts, then every 15 minutes. The desktop app also checks when you switch back to its window. To check straight away, or to change how often it checks, use **Check for changes** under *Linked library* in **Settings → Library**.

| You... | Scene Atlas... |
|--------|----------------|
| Add images | Adds them, sorted by Auto |
| Edit an image in place | Updates it, keeping its name, tags, group and any grid you set |
| Move or rename an image | Finds it at its new path and keeps everything you set |
| Delete an image | Marks it **File missing**. Its name, tags and thumbnail are kept in case it comes back |

To clear out images whose files are gone, use **Remove missing images** in **Settings → Library**.

### When the linked library isn't there

If the folder is on a drive or network share that isn't connected, a banner says it isn't available. Search, thumbnails and editing still work, but full-size images can't be opened until the folder is back. Nothing is marked missing while the whole folder is gone.

### Unlinking

**Desktop app:** **Settings → Library → Unlink** removes the library's images from Scene Atlas, with their tags and groups. Your files are not touched.

**Server:** unset `SCENE_ATLAS_LINKED_LIBRARY_DIR` and restart. Settings then says the library is no longer linked; **Remove its images** in **Settings → Library** removes them from Scene Atlas.

## Backups

Scene Atlas doesn't back up your library by itself. Back up both *Imported images* and *Search data* with your usual backup tool, ideally while Scene Atlas is closed. A linked library is yours to back up.

**Settings → Library → Export metadata** saves your library's metadata to one file: the names, groups, tags and grids of every image, and the search data. It doesn't contain the images themselves, so keep it with a copy of *Imported images*. The desktop app asks where to save it; on a server your browser downloads it. A large library takes a few minutes, and the file is a few KB per image.

### Rebuilding from a backup

**Settings → Library → Rebuild from export…** replaces your library's metadata with a file from **Export metadata**: after losing *Search data*, say, or to go back to an earlier state. It doesn't merge: the library becomes what the export holds.

1. Choose the export. Scene Atlas reads it and tells you what would change: images in the export whose files aren't in your library any more (they're left out), and images in your library that aren't in the export (they'll be lost). Open each line to see which groups and images.
2. Choose **Rebuild**. The new library is built alongside the current one, which you can keep using meanwhile. Nothing changes yet, and **Cancel** still leaves everything as it was.
3. Choose **Restart now**. Scene Atlas restarts into the rebuilt library. On a server, it stops and your service manager starts it again (Docker Compose does, with `restart: unless-stopped`).

After the restart, image files the export didn't have are moved to `not-in-backup/` inside *Imported images*, in folders named like a download, so you can see what they are and import them again. The previous library's database is kept in `rebuild/` inside *Search data* until the next rebuild. Changes made between choosing **Rebuild** and the restart aren't in the rebuilt library.

The export can be from another library (a warning says so): what matters is that the image files are here. If the search model has changed since the export, images are processed again afterwards.

Before an update changes the structure of its database, Scene Atlas saves a copy of it in `backups/pre-migration/` inside *Imported images*.

To go back to an older version of Scene Atlas after an update, install the older version and restore the newest backup from `backups/pre-migration/`. A database upgraded by a newer version can't be opened by an older one.

## Moving the library

Scene Atlas doesn't move its files for you yet.

**Desktop app:**

1. Close Scene Atlas, then copy the folder to its new place.
2. Start Scene Atlas. In **Settings → Storage locations**, choose the new folder. It should say *Scene Atlas library found.*
3. Choose **Restart to apply** under the folder you changed.
4. Once your library opens from the new place, delete the old folder.

Scene Atlas checks that *Search data* and *Imported images* belong to the same library and refuses to start if they don't. If the desktop app can't open the library, it offers **Try again** and **Choose folders…**.

**Server:** stop it, move the folders, update `SCENE_ATLAS_DATA_DIR` and `SCENE_ATLAS_IMAGES_DIR`, and start it again.

## Opening an existing library

On a new computer or after a reinstall, point the desktop setup's library step at an existing *Imported images* or *Search data* folder. Scene Atlas recognises it, fills in the other folder and offers **Open library**.

## Downloading

**Download** on a group's menu, in the image viewer, or for the groups selected in the group editor saves them as a ZIP. Inside, each group of two or more images has a folder named `Author_Group`, and each file is named from its group, name, grid and tags, for example `Czepeku_Golden Forest_Day_G30x30[forest,summer].webp` (`G30x30` is a square grid, `HG` a hex grid, `GL` no grid). A `scene-atlas.jsonl` file holds each image's name, group, tags, grid and search data.

A download holds at most 999 images and 2 GB. Downloading a single image from the viewer or its menu saves just that file, named the same way.

## Exporting the whole library

**Settings → Library → Export library** copies every image into a folder, laid out like a download, with its `scene-atlas.jsonl`. The files are ordinary images in folders named after their groups, so they're yours to use without Scene Atlas; importing the folder (or a ZIP of it) into Scene Atlas brings everything back, names, groups, tags, grids and search data included.

- **Desktop app:** choose an empty folder. It needs as much free space as your images take: *Imported images*, plus the linked library unless you leave it out.
- **Server:** it's written into `exports/` inside `SCENE_ATLAS_IMAGES_DIR`, and Settings shows where. Copy it off the server from there, then delete it: the server keeps one export at a time, and a backup of the images folder would copy it too.

Each file is checked against the library's record of it as it's copied. Files that can't be read are skipped, listed when it's done, and written to `scene-atlas-export-problems.txt` in the folder. A large library takes as long as copying its files: hours for a terabyte. If it stops (a full disk, the computer turned off), make room and choose **Carry on**: it picks up where it got to. **Carry on** after a finished export adds the groups that are new since. It doesn't retry files that were skipped in groups it has already written; export into a new folder for those. If you have a linked library, you can leave its images out, since you have those files already.

The [`export_library` command](/reference/cli#export-the-library) does the same from the command line.

## Starting over

**Settings → Library → Delete library** removes every image, tag and search entry. It can't be undone. Files in a linked library are not touched.

**Reset tags** in the same place removes every tag from every image and puts tag categories back to the Common pack.
