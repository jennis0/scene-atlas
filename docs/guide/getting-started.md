# Installation

Choose the path that fits your setup. All three options give you the same features.

## Desktop App

Best for personal use on a single machine.

1. **Download** the latest installer from [GitHub Releases](https://github.com/joe-ennis/scene-atlas/releases):
   - Windows: `.exe` (NSIS installer)
   - macOS: `.dmg` (universal binary — Intel + Apple Silicon)
   - Linux: `.AppImage` or `.deb`

2. **Install and launch.** On first run, Scene Atlas downloads the AI model (~250 MB for the default small model). This only happens once.

3. **Choose your image directory.** Point Scene Atlas at the folder where your battlemap collection lives. It does not move or modify your files.

4. **Import your first images.** Click **Import** in the top bar, drag in some files, and let the processing run. See the [Importing guide](/guide/importing) for details.

### System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| RAM | 8 GB | 16 GB (for medium/large AI models) |
| Disk | 500 MB + your image library | SSD for faster search indexing |
| GPU | Not required | NVIDIA GPU for faster AI inference |

## Docker Server

Best for self-hosting on a home server or NAS, accessible from any device on your network.

### Quick Start

```bash
# Clone the repository (for docker-compose.yml)
git clone https://github.com/joe-ennis/scene-atlas.git
cd scene-atlas

# Create a directory for your images (or point to an existing one)
mkdir -p images

# Start with CPU inference
docker compose --profile cpu up -d
```

Open `http://localhost:8000` in your browser.

### With GPU Acceleration

```bash
# Requires nvidia-container-toolkit
docker compose --profile gpu up -d
```

See the [Docker Server guide](/deploy/server) for reverse proxy setup, CORS configuration, and more.

## Developer Mode

For contributors or anyone who wants to run from source with hot reload.

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with npm

### Quick Start

```bash
# Install dependencies
uv sync
cd frontend && npm ci && cd ..

# Download the AI model
uv run python scripts/models/setup_models.py

# Start both backend and frontend
make dev
```

- Backend API: `http://localhost:8000`
- Frontend dev server: `http://localhost:5173` (proxies API calls to :8000)

See the [Building & Running guide](/development/building) for pre-commit hooks, linting, and more.

## First Import

Once Scene Atlas is running:

1. Click **Import** in the top-right corner
2. Drag and drop images, folders, or ZIP archives into the upload area
3. Scene Atlas analyses your files — detecting groups, extracting metadata, generating AI embeddings
4. Browse your collection in the gallery, or start searching

::: tip
Scene Atlas automatically groups related map variants (snowy, fey, summer) based on filename patterns and folder structure. You can adjust groups after import.
:::

## Choosing an AI Model

Scene Atlas supports three AI model sizes. You can change the active model in **Settings** at any time — images are automatically re-embedded.

| Model | Dimensions | Size | Best for |
|-------|-----------|------|----------|
| **Small** (CLIP ViT-B/32) | 512 | ~250 MB | CPU-only machines, quick setup |
| **Medium** (SigLIP2-base) | 768 | ~500 MB | GPU-equipped machines, better accuracy |
| **Large** (SigLIP2-so400m) | 1152 | ~1 GB | Maximum accuracy, GPU strongly recommended |

## Troubleshooting

**Model download is slow:** The first download can take a few minutes on slower connections. Scene Atlas shows progress in the activity dock.

**Port 8000 already in use:** Set `PORT=8001` in your `.env` file (Docker) or pass `--port 8001` to uvicorn (standalone).

**CORS errors in browser console:** If running behind a reverse proxy, set `CORS_ORIGINS` to match your domain. See the [Configuration Reference](/deploy/configuration).
