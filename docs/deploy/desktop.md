# Desktop App

The desktop app bundles Scene Atlas into a single installer. No Docker, no Python, no command line. It runs the backend as a sidecar process and opens a native window.

## Download

Get the latest release from [GitHub Releases](https://github.com/joe-ennis/scene-atlas/releases).

| Platform | Format | Architectures | Gpu Support |
|----------|--------|---------------|---|
| Windows | NSIS installer (`.exe`) | x64 | Yes (DirectX12 GPU) |
| macOS | DMG (`.dmg`) | Universal (Intel + Apple Silicon) | Yes on Applie Silicon |
| Linux | AppImage (`.AppImage`) + DEB (`.deb`) | x64 | No |
| Docker | Build Yourself | Windows/Mac/Linux | Yes (via CUDA) |

## Installation

**Windows:** Run the installer. A desktop shortcut and Start Menu entry are created automatically.

**macOS:** Open the DMG and drag Scene Atlas to Applications.

**Linux:** Make the AppImage executable (`chmod +x Scene-Atlas-*.AppImage`) and run it, or install the `.deb` with `sudo dpkg -i Scene-Atlas-*.deb`.

## First Launch

On first launch, Scene Atlas will:

1. **Ask for a storage location** — choose where the app stores its data (database, thumbnails, search index). This is a dedicated directory managed by Scene Atlas, not your existing image folder. Your original files are copied into managed storage during import.
2. **Download an AI model** — the default model (~250 MB) is downloaded from HuggingFace. Progress is shown in the UI.
3. **Open the gallery** — once the model is ready, you can start importing images.

## System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| RAM | 8 GB free (with smaller imports) | 16 GB |
| App Data Disk | 2 GB + ~50% of your library size (for thumbnails, index, and converted copies) | SSD for faster indexing |
| Image Data Disk | As much storage as is required for your image files! | This can be slower HDD without significant performance loss |
| GPU | Not required | NVIDIA GPU (CUDA) for faster import processing |

## AI Models

You can change the active model at any time in **Settings**. Images are automatically re-embedded when you switch.

| Model | Size | GPU needed? | Quality |
|-------|------|-------------|---------|
| **Small** | ~250 MB | No | Good — works well on CPU |
| **Medium** | ~500 MB | Recommended | Better — noticeably more accurate but slower |
| **Large** | ~1 GB | Strongly recommended | Best search accuracy |

The app auto-selects a model based on your hardware. See the [Configuration Reference](/deploy/configuration) for model details.

## GPU Acceleration

Scene Atlas detects available GPU hardware automatically:

1. **CUDA** (NVIDIA GPUs) — fastest
2. **DirectML** (Windows, any GPU) — broad compatibility
3. **CoreML** (macOS, Apple Silicon)
4. **CPU** — fallback, always available

No manual configuration needed. To force a specific device, set `INFERENCE_DEVICE` in environment variables before launch.

## Data Locations

| Item | Location |
|------|----------|
| App configuration | `{userData}/scene-atlas-config.json` |
| Backend log | `{userData}/backend.log` |
| Default data directory | `{Documents}/Scene Atlas/data` |

Where `{userData}` is:
- **Windows:** `%APPDATA%/Scene Atlas`
- **macOS:** `~/Library/Application Support/Scene Atlas`
- **Linux:** `~/.config/Scene Atlas`

The data directory contains the SQLite database, LanceDB vector index, thumbnails, and backups.

## Auto-Updates

The app checks for updates via GitHub Releases. When a new version is available, you'll be prompted to download and install. Updates preserve your data and settings.

## Troubleshooting

**App won't start:** Check `{userData}/backend.log` for errors. The most common cause is a port conflict with another process.

**Model download fails:** Check your internet connection. You can retry from Settings.

**High memory usage:** The large model can use 2-4 GB of RAM. Switch to the small model in Settings if memory is tight.
