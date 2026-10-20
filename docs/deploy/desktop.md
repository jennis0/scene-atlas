# Desktop App

The desktop app bundles Scene Atlas into a single installer. It runs the backend as a sidecar process and opens a native window.

## Download

Get the latest release from [GitHub Releases](https://github.com/jennis0/scene-atlas/releases).

| Platform | Format | Architectures | GPU acceleration |
|----------|--------|---------------|---|
| Windows | NSIS installer (`.exe`) | x64 | Yes (DirectML, any DirectX 12 GPU) |
| macOS | DMG (`.dmg`) | Apple Silicon (arm64) only | Yes (CoreML) |
| Linux | AppImage (`.AppImage`) + DEB (`.deb`) | x64 | No (CPU only) |

There is a single installer per platform; the Windows build includes DirectML support. Intel Macs are not supported by the desktop app; use the [Docker](/deploy/server) or [standalone](/deploy/standalone) server instead. For NVIDIA CUDA acceleration, use the Docker server with the `gpu` profile.

## Installation

**Windows:** Run `Scene-Atlas-Setup-<version>.exe`. A desktop shortcut and Start Menu entry are created automatically.

**macOS:** Open the DMG and drag Scene Atlas to Applications.

**Linux:** Make the AppImage executable (`chmod +x Scene-Atlas-*.AppImage`) and run it, or install the `.deb` with `sudo dpkg -i Scene-Atlas-*.deb`.

## First-Launch Warnings

The installers aren't code-signed yet, so Windows and macOS can't confirm who made them and warn you the first time you open Scene Atlas. You only need to do this once.

**Windows:** If you see "Windows protected your PC", select **More info**, then **Run anyway**.

**macOS:** If macOS says Scene Atlas "can't be opened" or "could not be verified", select **Done**. Open **System Settings → Privacy & Security**, scroll down and select **Open Anyway** next to the message about Scene Atlas, then confirm with your password.

If macOS says Scene Atlas "is damaged and can't be opened", the app isn't damaged: macOS says this about some unsigned downloads. Run this in Terminal, then open Scene Atlas again:

```bash
xattr -dr com.apple.quarantine "/Applications/Scene Atlas.app"
```

## First Launch

On first launch, Scene Atlas opens its setup steps:

1. **Appearance.** Choose a theme and text size.
2. **Your library.** Start a new library, or use a folder of maps you already have. Scene Atlas reads that folder where it is and never changes, moves or deletes your files. You can also choose where two folders go:
   - *Imported maps*: full-size copies of maps you import in the app, plus backups. Any large drive will do.
   - *Search data*: the database, thumbnails and search index. Best on a fast drive.

   A new library defaults to `Scene Atlas` in your local app data folder on Windows (`%LOCALAPPDATA%\Scene Atlas`, which OneDrive never syncs) and to `Documents/Scene Atlas/` on macOS and Linux. Pointing the step at an existing Scene Atlas library opens it. If you change the folders, the app restarts its backend in the same window.
3. **The rest of setup.** Choose how imported images are stored, which tag packs to start with, and a search model. A model is recommended for your hardware.
4. **Open the gallery.** The model downloads from Hugging Face in the background; once it's ready, you can start importing images.

## System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| OS | Windows 10 (64-bit), macOS 13 Ventura (Apple Silicon), or a 64-bit Linux desktop | |
| RAM | 8 GB | 16 GB |
| App Data Disk | 2 GB + ~50% of your library size (for thumbnails, index, and converted copies) | SSD for faster indexing |
| Image Data Disk | As much storage as is required for your image files! | This can be slower HDD without significant performance loss |
| GPU | Not required | DirectX 12 GPU (Windows) or Apple Silicon (macOS) for faster import processing |

## AI Models

You can change the active model at any time in **Settings**. Images are automatically re-embedded when you switch.

| Model | Size | GPU needed? | Quality |
|-------|------|-------------|---------|
| **Small** | ~250 MB | No | Good:works well on CPU |
| **Medium** | ~500 MB | Recommended | Better:noticeably more accurate but slower |
| **Large** | ~1 GB | Strongly recommended | Best search accuracy |

The app auto-selects a model based on your hardware. See the [Configuration Reference](/deploy/configuration) for model details.

## GPU Acceleration

Scene Atlas detects available GPU hardware automatically. You don't need an NVIDIA GPU:

- **Windows:** DirectML works with any DirectX 12 GPU (NVIDIA, AMD, Intel).
- **macOS:** CoreML accelerates inference on Apple Silicon.
- **Linux (desktop):** CPU inference only. NVIDIA CUDA is available via the Docker server.
- **CPU** is always available as a fallback on all platforms.

No manual configuration needed. To force a specific device, set `INFERENCE_DEVICE` in environment variables before launch.

## Data Locations

| Item | Location |
|------|----------|
| App configuration | `{userData}/scene-atlas-config.json` |
| Backend log | `{userData}/backend.log` |
| App data and image library | Chosen during first launch (default `data` and `images` in `%LOCALAPPDATA%\Scene Atlas` on Windows, `Documents/Scene Atlas` on macOS and Linux) |
| Backend application log | `<app data>/logs/scene-atlas.log` |

Where `{userData}` is:
- **Windows:** `%APPDATA%/Scene Atlas`
- **macOS:** `~/Library/Application Support/Scene Atlas`
- **Linux:** `~/.config/Scene Atlas`

The app data directory contains the SQLite database, LanceDB vector index, and thumbnails. Backups are written to `<image library>/backups/`. Both locations can be changed later in **Settings**.

## Updates

You choose how Scene Atlas updates during setup, and can change it in **Settings → Updates**:

- **Automatic:** downloads new versions and installs them when you restart.
- **Ask first** (the default): tells you when a new version is out. Nothing downloads or installs until you press **Update**.
- **Off:** only checks when you press **Check now**.

Scene Atlas doesn't check for updates until you've made this choice or finished setup.

| Installed from | Updating |
|---|---|
| Windows installer (`.exe`) | **Update** (or Automatic) downloads it in the background; **Restart to update** installs it, or it installs when you quit. |
| Linux `.AppImage` | The same. The new version replaces the file, with the new version number in its name, so update any shortcut to it. |
| macOS (`.dmg`), Linux `.deb` | Says a new version is out and links to its download; there is no Automatic. Install it over the existing version. |

Your data directories and settings are kept, and the database is backed up before an update changes its structure. Going back to an older version means restoring that backup.

## Troubleshooting

**App won't start:** Check `{userData}/backend.log` for errors. The backend picks a free port automatically, so check for a missing or unreadable data directory first.

**Model download fails:** Check your internet connection. You can retry from Settings.

**High memory usage:** The large model can use 2-4 GB of RAM. Switch to the small model in Settings if memory is tight.
