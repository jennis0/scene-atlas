# Settings

Open Settings with the gear icon in the top bar. It has three tabs: **Library**, **Appearance** and **Settings**. Changes on the Settings tab are saved when you switch tab or close the dialog.

On a shared server, Library and Settings apply to everyone; Appearance is per device.

## Library

![The Library tab: image, group and storage totals, the linked Images folder with Check for changes and How often to check, Export library, and Delete library and Reset tags](/screenshots/settings-library.webp)

- **Images, Groups and Storage**: how much is in the library, and how much disk it uses for images, search data and the rest.
- **Export library**: download every image as a ZIP. See [Exporting](/guide/library#exporting).
- **Images folder** (only when [your own folder](/guide/library#using-your-own-folder) is linked): whether it's available, **Check for changes**, **How often to check**, **Remove missing images** (when files have gone) and, in the desktop app, **Stop using this folder**. On a server, once `LINKED_LIBRARY_DIR` is unset, **Remove its images** clears out the folder's images. See [Using your own folder](/guide/library#using-your-own-folder).
- **Delete library**: remove every image, tag and search entry. It can't be undone.
- **Reset tags**: remove every tag from every image and go back to the Common tag pack. It can't be undone.

## Appearance

These choices affect only this device.

| Setting | Options |
|---------|---------|
| Mode | System, Light, Dark. The sun/moon button in the top bar also switches |
| Palette | Navy, Green, Slate, Brown, Plum |
| Text size | Small, Default, Large, Larger. Makes text and controls bigger; images stay the same |
| Contrast | Auto, Standard, High. High gives bolder text and outlines |
| Zoom (desktop app) | 80–200%. Makes everything bigger, images included. `Ctrl`/`Cmd` `+` and `-` also zoom |
| Compact header | Auto, On, Off. Fits the header into two rows; Auto does this on small windows |

## Settings

### Storage locations (desktop app)

Where the library's folders are: **Search data**, **Imported images** and, if you use one, **Images folder** (your own folder). Choose a new folder, then **Restart now to apply**. Changing a folder doesn't move your files; see [Moving the library](/guide/library#moving-the-library).

![Storage locations: Search data, Imported images and Images folder, each with Change; Images folder also has Stop using](/screenshots/settings-storage.webp)

On a server, folders are set with environment variables; see the [Configuration Reference](/deploy/configuration#storage).

### Updates

**Desktop app:** **New versions** sets how Scene Atlas updates:

- **Automatic**: downloads new versions and installs them when you restart.
- **Ask first** (default): tells you when a new version is out. Nothing installs until you choose.
- **Off**: only checks when you press **Check now**.

See [Desktop App: Updates](/deploy/desktop#updates) for how each installer updates.

**Server:** shows the running version and whether a newer release is out, with links to its notes and the upgrade guide. The server's administrator updates it; see [Docker Server: Updating](/deploy/server#updating).

### Search Model

The model that understands images and descriptions. Larger models find better matches but make importing slower.

| Model | Download | Best for |
|-------|----------|----------|
| Small | ~250 MB | Any computer; works well without a GPU |
| Medium | ~500 MB | Better matches; faster with a GPU |
| Large | ~1 GB | The best matches; needs a GPU to import at a reasonable speed |

Click a model, then **Confirm switch**. Every image is processed again with the new model, which takes a while for a large library; imports in progress pause until it's done.

**Stale Embeddings** lists models you've used before. **Delete embeddings** frees the space they take; switching back to that model later processes every image again.

### General

- **Grid detection**: look for grids on imported battlemaps. Grid sizes in filenames are read either way.
- **Grid analysis resolution**: **Full** (default) finds thin grid lines on high-resolution maps. **8K** and **4K** shrink larger maps first, which is faster but can miss them.
- **Colour match**: how close an image's colours must be to a colour filter. **Close**, **Similar** (default) or **Broad**.

### Tag Packs

Add [tag packs](/guide/tags#tag-packs) you didn't choose during setup.

### Import Limits

| Setting | Default | |
|---------|---------|---|
| Max file size | 2 GB | Larger images aren't imported |
| Max video size | 2 GB | Larger videos aren't imported |
| Max files per zip | 1,000 | Per ZIP archive |
| Max zip size (uncompressed) | 2 GB | Per ZIP archive, once unpacked |
| Stored format | Original | See [Stored Format](/guide/importing#stored-format) |
| Quality | 90 | WebP and JPEG only |
| Lossless WebP for PNGs | On | WebP only |

### Performance

**Parallel image processing** is how many images are prepared at once across all imports. More is faster up to about 4; beyond that, imports gain little and the app is slow while they run. Takes effect after a restart.

Other tuning settings have no controls; see [Runtime Settings](/deploy/configuration#runtime-settings).
