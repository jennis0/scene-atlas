<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-dark.png">
    <img src="assets/brand/lockup-light.png" alt="Scene Atlas" width="405">
  </picture>
</p>

<p align="center"><strong>Find any map in your collection by describing it.</strong></p>

<p align="center">
  <a href="#download">Download</a> ·
  <a href="docs/guide/what-is-scene-atlas.md">Guide</a> ·
  <a href="#run-it-on-a-server">Self-hosting</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

Scene Atlas organises and searches large collections of battlemaps and scene art. Type "a snowy ruined temple at night" and it finds the maps that look like that, whatever the files are called. It runs on your own computer, or on your own server.

## What it does

- **Search by description.** Describe what you're after and get the maps that look like it. Narrow it down with keywords, tags, colour and grid type.
- **Variants kept together.** The day, night, snowy and gridless versions of a map sit together as one scene.
- **Battlemaps and scenes.** Battlemaps get their grid detected. Vistas, portraits and encounter art are kept alongside them.
- **Tags that fit your games.** Start from packs for fantasy, sci-fi, horror, cyberpunk or historical play, then add your own.
- **Built for big libraries.** Tested on a library of 56,000 images.

## Your data stays with you

Your images, your library and your searches stay on your machine. There are no accounts and no analytics. Scene Atlas goes online only to download its search model from Hugging Face.

## Download

Get the installer for your computer from [Releases](https://github.com/jennis0/scene-atlas/releases).

| System | Download |
|---|---|
| Windows 10 or later | `.exe` installer (x64) |
| macOS 13 or later | `.dmg`, Apple Silicon only |
| Linux | `.AppImage` or `.deb` (x64) |

The installers aren't signed yet, so Windows and macOS warn you the first time you open Scene Atlas. [How to open it anyway](docs/deploy/desktop.md#first-launch-warnings).

> No release has been published yet. Until the first one, run Scene Atlas [from source](docs/development/building.md).

You'll need 8 GB of RAM (16 GB recommended), and room on disk for a copy of your images.

## Run it on a server

Run Scene Atlas on a home server to reach your library from anywhere:

```bash
git clone https://github.com/jennis0/scene-atlas.git
cd scene-atlas
docker compose --profile cpu up -d     # --profile gpu for an NVIDIA GPU
```

Then open http://localhost:8000. Scene Atlas has no sign-in of its own, so put it behind a reverse proxy that handles sign-in before you open it up beyond your own network. See [Docker server](docs/deploy/server.md).

## Documentation

- **Using it:** [getting started](docs/guide/getting-started.md), [importing](docs/guide/importing.md), [searching](docs/guide/searching.md), [groups](docs/guide/groups.md), [tags](docs/guide/tags.md)
- **Installing it:** [desktop app](docs/deploy/desktop.md), [Docker server](docs/deploy/server.md), [standalone server](docs/deploy/standalone.md), [configuration](docs/deploy/configuration.md)

## Contributing

Bug reports and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers setting up a development environment, and [design/](design/README.md) explains how Scene Atlas is built.

## Licence

MIT. See [LICENSE](LICENSE). The Cinzel and Figtree fonts are under the SIL Open Font License.
