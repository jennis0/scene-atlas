# Desktop App

The desktop app bundles Scene Atlas into a single installer — no Docker, no Python, no command line. It runs the full backend as a sidecar process and opens a native window.

## Download

Download the latest release from [GitHub Releases](https://github.com/joe-ennis/scene-atlas/releases).

| Platform | Format | Architectures |
|----------|--------|---------------|
| Windows | NSIS installer (`.exe`) | x64 |
| macOS | DMG (`.dmg`) | Universal (Intel + Apple Silicon) |
| Linux | AppImage (`.AppImage`) + DEB (`.deb`) | x64 |

## Installation

**Windows:** Run the installer. You can choose a custom install directory. A desktop shortcut and Start Menu entry are created automatically.

**macOS:** Open the DMG and drag Scene Atlas to Applications.

**Linux:** Make the AppImage executable (`chmod +x Scene-Atlas-*.AppImage`) and run it, or install the `.deb` with `sudo dpkg -i Scene-Atlas-*.deb`.

## First Launch

On first launch, Scene Atlas will:

1. **Ask for your image directory** — the folder where your battlemap collection lives. Scene Atlas does not move or modify your original files.
2. **Download an AI model** — the default small model (~250 MB) is downloaded from HuggingFace. Progress is shown in the UI.
3. **Open the gallery** — once the model is ready, you can start importing images.

## System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| RAM | 8 GB | 16 GB (medium/large models) |
| Disk | 500 MB + image library | SSD recommended |
| GPU | Not required | NVIDIA GPU (CUDA) for faster inference |

## Choosing an AI Model

You can change the active model at any time in **Settings**. Images are automatically re-embedded when you switch.

| Model | Size | GPU Required? | Quality |
|-------|------|--------------|---------|
| **Small** (CLIP ViT-B/32) | ~250 MB | No | Good — best for CPU-only |
| **Medium** (SigLIP2-base) | ~500 MB | Recommended | Better — noticeably more accurate |
| **Large** (SigLIP2-so400m) | ~1 GB | Strongly recommended | Best — highest search accuracy |

## GPU Acceleration

Scene Atlas automatically detects available GPU hardware and uses the best provider:

1. **CUDA** (NVIDIA GPUs) — fastest option
2. **DirectML** (Windows, any GPU) — broad compatibility
3. **CoreML** (macOS) — Apple Silicon acceleration
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

The data directory contains the SQLite database, LanceDB vector index, thumbnails, and backups. Your original images stay where you pointed the app — they are never copied into the data directory.

## Auto-Updates

The desktop app checks for updates via GitHub Releases. When a new version is available, you'll be prompted to download and install it. Updates preserve your data and settings.

## Troubleshooting

**App won't start:** Check `{userData}/backend.log` for errors. The most common cause is a port conflict — the backend runs on a local port that another process may be using.

**Model download fails:** Check your internet connection. The model is downloaded from HuggingFace (~250 MB–1 GB depending on model). You can retry from Settings.

**High memory usage:** The large AI model can use 2–4 GB of RAM. Switch to the small model in Settings if memory is constrained.
