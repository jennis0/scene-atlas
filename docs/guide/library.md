# Your Library

A Scene Atlas library is stored in up to three folders:

| Place | Holds | Desktop default | Server setting |
|-------|-------|-----------------|----------------|
| **Search data** | Database, thumbnails, search index, AI models, logs | `%LOCALAPPDATA%\Scene Atlas\data` (Windows), `Documents/Scene Atlas/data` (macOS, Linux) | `SCENE_ATLAS_DATA_DIR` |
| **Imported images** | Full-size copies of images you import, and backups | `…\Scene Atlas\images`, or `<linked library>\Scene Atlas` when you link one | `SCENE_ATLAS_IMAGES_DIR` |
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

Scene Atlas backs up its database and search index once a day to `backups/` inside *Imported images*. It keeps the 7 most recent and up to 4 older ones, one a week. It also saves a copy of the database before an update changes its structure, in `backups/pre-migration/`.

Backups don't include your images. Back up *Imported images* (which holds both the images and the backups) with your usual backup tool. A linked library is yours to back up.

### Restoring a backup

1. Close Scene Atlas (or stop the server).
2. In *Search data*, rename `battlemap.db` to keep it, for example `battlemap.db.old`.
3. Copy `battlemap.db` from the backup folder you want into *Search data*.
4. Start Scene Atlas.

::: warning
Images imported after the backup was taken aren't in the restored database, and the daily cleanup deletes their files from *Imported images*. Import them again afterwards if you still have the originals.
:::

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

## Exporting

**Settings → Library → Export library** downloads every image as a ZIP, in folders by author and group, with readable file names and a `metadata.json` of each image's name, tags and grid. It includes images from a linked library. For a very large library, the [`export_library` command](/reference/cli#export-the-library) writes the same thing straight to a folder.

## Starting over

**Settings → Library → Delete library** removes every image, tag and search entry. It can't be undone. Files in a linked library are not touched.

**Reset tags** in the same place removes every tag from every image and puts tag categories back to the Common pack.
