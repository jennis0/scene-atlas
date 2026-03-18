# Installation

All three deployment options give you the same features. Pick the one that fits.

## Desktop App

Download, install, and run. No dependencies to manage.

1. **Download** the installer from [GitHub Releases](https://github.com/joe-ennis/scene-atlas/releases):
   - Windows: `.exe` (NSIS installer)
   - macOS: `.dmg` (universal, Intel + Apple Silicon)
   - Linux: `.AppImage` or `.deb`

2. **Install and launch.** On first run, Scene Atlas downloads an AI model (~250 MB). This happens once.

3. **Choose a storage location.** The app asks where to keep its data (database, thumbnails, search index). This is a dedicated directory that Scene Atlas manages internally. Your original images are never modified; they are copied into managed storage during import.

4. **Import your first images.** Click **Import**, drag in some files, and let processing run. See [Importing](/guide/importing) for details.

::: tip
The app auto-selects an AI model based on your hardware. You can switch models later in **Settings** if you want higher accuracy or lower memory usage.
:::

### System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| RAM | 8 GB | 16 GB |
| App Data Disk | 2 GB + ~50% of your library size (for thumbnails, index, and converted copies) | SSD for faster indexing |
| Image Data Disk | As much storage as is required for your image files! |  |
| GPU | Not required | Any modern GPU speeds up import processing (NVIDIA, AMD, Intel on Windows; Apple Silicon on Mac) |

## Docker Server

For self-hosting on a home server or NAS.

```bash
git clone https://github.com/joe-ennis/scene-atlas.git
cd scene-atlas

# CPU inference
docker compose --profile cpu up -d

# Or with NVIDIA GPU (requires nvidia-container-toolkit)
docker compose --profile gpu up -d
```

Open `http://localhost:8000` in your browser.

The container uses two volumes:
- **`scene-atlas-data`** (named volume) for the database, vector index, and thumbnails
- **`./images`** (bind mount, configurable via `IMAGE_DIR` in `.env`) for Scene Atlas's managed image storage

::: warning
The `IMAGE_DIR` path is where Scene Atlas writes its managed file structure. Do not point it at your existing image collection. Import your images through the web UI instead.
:::

See the [Docker Server guide](/deploy/server) for reverse proxy setup, authentication, and backups.

## Developer Mode

For contributors or anyone running from source.

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with npm

### Quick Start

```bash
# Install dependencies
uv sync --extra dev --extra cpu
cd frontend && npm ci && cd ..

# Download the AI model
uv run python scripts/models/setup_models.py

# Terminal 1: backend
uv run python scripts/start.py

# Terminal 2: frontend
cd frontend && npm run dev
```

- Backend API: `http://localhost:8000`
- Frontend dev server: `http://localhost:5173` (proxies API calls to :8000)

See the [Building & Running guide](/development/building) for pre-commit hooks, linting, and build targets.

## First Import

Once Scene Atlas is running:

1. Click **Import** in the top-right corner
2. Drag and drop images, folders, or ZIP archives into the upload area
3. Review the detected groups and metadata, then confirm
4. Browse or search your collection in the gallery

Scene Atlas automatically groups related map variants by filename patterns and folder structure. You can adjust groups before or after confirming the import.

## Troubleshooting

**Model download is slow:** The initial download can take a few minutes depending on your connection. Progress is shown in the activity dock.

**Port 8000 already in use:** Set `PORT=8001` in your `.env` file, or pass `--port 8001` to uvicorn.

**CORS errors in browser console:** If running behind a reverse proxy, set `CORS_ORIGINS` to match your domain. See the [Configuration Reference](/deploy/configuration).
