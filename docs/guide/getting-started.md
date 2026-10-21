# Installation

Scene Atlas runs as a desktop app or as a server you open in a browser.

| | Desktop app | Docker server | Standalone server |
|---|---|---|---|
| For | Using it on your own computer | A home server or NAS, used from anywhere | Servers without Docker |
| Install | An installer | `docker compose` | Python and Node.js from source |
| Imports | Read straight from your disk | Uploaded from the browser | Uploaded from the browser |
| Your own folder | Chosen in setup or Settings | A read-only mount | An environment variable |
| Sign-in | Not needed | Add a reverse proxy | Add a reverse proxy |
| GPU | DirectML (Windows), CoreML (Mac) | NVIDIA | NVIDIA, DirectML or CoreML |

Search, groups, tags and everything else in the gallery are the same in each.

## Desktop App

1. Download the installer for your system from [GitHub Releases](https://github.com/jennis0/scene-atlas/releases): `.exe` for Windows, `.dmg` for Apple Silicon Macs, `.AppImage` or `.deb` for Linux.
2. Install and open it. The installers aren't signed yet, so [Windows and macOS warn you the first time](/deploy/desktop#first-launch-warnings).
3. Follow the setup:
   - **Appearance**: theme, text size and how the app updates.
   - **Your library**: start a new library, or use a folder of images you already have. See [Your Library](/guide/library).
   - **Stored format**: keep imported images as they are, or convert them to WebP to save space.
   - **Tag packs**: ready-made tags for the genres you play.
   - **Search model**: a model is recommended for your computer. It downloads in the background once you finish.

Full details, including system requirements: [Desktop App](/deploy/desktop).

## Docker Server

```bash
mkdir scene-atlas && cd scene-atlas
curl -fsSLO https://github.com/jennis0/scene-atlas/releases/latest/download/docker-compose.yml
curl -fsSL -o .env https://github.com/jennis0/scene-atlas/releases/latest/download/env.example
mkdir images
docker compose --profile cpu up -d
```

Open `http://localhost:8000` and follow the same setup, without the update and library choices.

::: danger No built-in sign-in
Anyone who can reach the server can see, change and delete your library. Put it behind a reverse proxy that asks for a login before anyone else can reach it.
:::

Full details, including GPU, reverse proxy and backups: [Docker Server](/deploy/server).

## Standalone Server

For running from source without Docker: [Standalone Server](/deploy/standalone).

To work on Scene Atlas itself, see [Building & Running](/development/building).

## Your First Import

1. Click **Import** in the top bar.
2. Leave **Import these as** on **Auto**, then drop in a folder of maps.
3. Close the dialog if you like; the import carries on, and images appear in the gallery as they finish.
4. When it's done, open the report and use **Review in editor** to check the groups.

See [Importing](/guide/importing) for the details, or [Your Library](/guide/library) to use a folder where it is instead.

## Troubleshooting

See [Troubleshooting](/reference/troubleshooting).
