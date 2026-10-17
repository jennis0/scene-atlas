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

**Windows:** Run the installer. A desktop shortcut and Start Menu entry are created automatically.

**macOS:** Open the DMG and drag Scene Atlas to Applications.

**Linux:** Make the AppImage executable (`chmod +x Scene-Atlas-*.AppImage`) and run it, or install the `.deb` with `sudo dpkg -i Scene-Atlas-*.deb`.

## First Launch

On first launch, Scene Atlas will:

1. **Ask for storage locations.** Choose an *app data location* (database, thumbnails, search index, logs) and an *image library location* (Scene Atlas's managed copy of your images, plus backups). Both default to `Documents/Scene Atlas/`. These are directories managed by Scene Atlas, not your existing image folder; files are copied into the library during import. If a folder you pick already holds other files, the app warns you and offers to choose another.
2. **Walk through setup.** Choose a theme and text size, how imported images are stored, which tag packs to start with, and a search model. A model is recommended for your hardware.
3. **Open the gallery.** The model downloads from Hugging Face in the background; once it's ready, you can start importing images.

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
| App data and image library | Chosen during first launch (default `Documents/Scene Atlas/data` and `Documents/Scene Atlas/images`) |
| Backend application log | `<app data>/logs/scene-atlas.log` |

Where `{userData}` is:
- **Windows:** `%APPDATA%/Scene Atlas`
- **macOS:** `~/Library/Application Support/Scene Atlas`
- **Linux:** `~/.config/Scene Atlas`

The app data directory contains the SQLite database, LanceDB vector index, and thumbnails. Backups are written to `<image library>/backups/`. Both locations can be changed later in **Settings**.

## Updates

The app does not update itself. Download new versions from [GitHub Releases](https://github.com/jennis0/scene-atlas/releases) and install over the existing version; your data directories and settings are kept.

## Troubleshooting

**App won't start:** Check `{userData}/backend.log` for errors. The backend picks a free port automatically, so check for a missing or unreadable data directory first.

**Model download fails:** Check your internet connection. You can retry from Settings.

**High memory usage:** The large model can use 2-4 GB of RAM. Switch to the small model in Settings if memory is tight.
