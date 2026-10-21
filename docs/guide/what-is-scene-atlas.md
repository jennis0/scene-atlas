# What is Scene Atlas?

Scene Atlas is a library for tabletop RPG art you already own: battlemaps, vistas, portraits and encounter art. It finds images by what's in them, not what the files are called, and keeps the variants of each map together.

![Searching for "woodland path at night": groups of battlemap variants, each led by its night-time version](/screenshots/search.webp)

*Maps by [Moonlight Maps](https://www.moonlight-maps.com) (CC BY-NC-SA 4.0), [2-Minute Tabletop](https://2minutetabletop.com) (CC BY-NC 4.0) and [Fantasy Atlas](https://www.patreon.com/fantasy_atlas) (CC BY-NC 4.0). This screenshot is shared under CC BY-NC-SA 4.0.*

## The Problem

If you run tabletop games, you probably have thousands of maps in nested folders from dozens of artists. Finding the right one mid-session means scrolling through directories, guessing at filenames or settling for whatever's close enough.

## How Scene Atlas Helps

**Bring in your collection.** Import files, folders or ZIPs, or point Scene Atlas at the folder you already keep your maps in and it reads them where they are. Each image is sorted into battlemaps or scenes, and tokens and other art are left out.

**Search by description.** Type "a dark cave with glowing mushrooms" and get caves with glowing mushrooms, whatever the files are called. Names, authors and tags are searched at the same time.

**Browse by scene.** The snowy, night and gridless versions of a map are grouped together, so you scan by scene rather than by file.

## Key Capabilities

- **Search by description**, combined with names, authors and tags
- **Your own folder, read in place**: no second copy, and new maps are picked up as you add them
- **Automatic sorting** of maps and scenes, skipping tokens and other art
- **Automatic grouping** of variants by folder and filename
- **Grid detection** for square and hex grids, with an overlay to check it
- **Tags** with genre packs (Fantasy, Sci-Fi, Cyberpunk, Horror, Historical), your own categories and aliases
- **Filters** by tag, author, grid, colour and media type
- **Animated maps**: MP4 and WebM, searched by their first frame
- **Built for big libraries**: tens of thousands of images in one import

## Scope

Scene Atlas organises art you already have. It is not a virtual tabletop, a map editor or a cloud service. It runs on your computer or your own server, and your images never leave it.

## Supported Platforms

| Platform | Desktop App | Docker Server | Standalone Server |
|----------|:-----------:|:-------------:|:-----------------:|
| Windows  | Installer | Docker Desktop | From source |
| macOS    | Apple Silicon only | Docker Desktop | From source |
| Linux    | AppImage, DEB | Docker | From source |

## Licence

Scene Atlas is free and open source under the [MIT licence](https://github.com/jennis0/scene-atlas/blob/main/LICENSE).

## Next Steps

Head to [Installation](/guide/getting-started) to get running.
