# Standalone Server

Run Scene Atlas directly on your machine without Docker. Useful when Docker is unavailable or you want more control over the runtime.

::: danger No built-in authentication
Scene Atlas has no login or access control. If anything other than your own machine can reach the port, put it behind a reverse proxy that authenticates users (basic auth, forward-auth, or an OAuth proxy) and never expose it directly to the internet. For local-only use, bind to `127.0.0.1` instead of `0.0.0.0`.
:::

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/)
- **Node.js 24+** with npm

## Installation

```bash
git clone https://github.com/jennis0/scene-atlas.git
cd scene-atlas
git checkout v<version>      # the latest release, from https://github.com/jennis0/scene-atlas/releases

# Install Python dependencies (pick one)
uv sync --extra cpu          # CPU-only inference
uv sync --extra gpu          # NVIDIA GPU (requires CUDA toolkit)
uv sync --extra gpu-directml # DirectX 12 GPU (Windows)

# Build the frontend
cd frontend && npm ci && npm run build && cd ..

# Download the AI model
uv run python scripts/models/setup_models.py
```

::: warning
A bare `uv sync` does not install an inference runtime. You must specify one of the extras above or the app will fail at startup.
:::

## Running

```bash
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
```

Open `http://localhost:8000` in your browser.

### Configuration

Set environment variables or create a `.env` file:

```bash
APP_DATA_DIR=./data
IMAGE_LIBRARY_DIR=./images
CORS_ORIGINS=["http://localhost:8000"]
```

`IMAGE_LIBRARY_DIR` is where Scene Atlas stores imported images in its own file structure. Do not point it at your existing collection.

See the [Configuration Reference](/deploy/configuration) for all settings.

## Running as a System Service

### systemd (Linux)

Create `/etc/systemd/system/scene-atlas.service`:

```ini
[Unit]
Description=Scene Atlas
After=network.target

[Service]
Type=simple
User=scene-atlas
WorkingDirectory=/opt/scene-atlas
Environment=APP_DATA_DIR=/var/lib/scene-atlas
Environment=IMAGE_LIBRARY_DIR=/var/lib/scene-atlas/images
ExecStart=/opt/scene-atlas/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now scene-atlas
```

## Reverse Proxy

The same configurations from the [Docker Server guide](/deploy/server#reverse-proxy) apply, including the authentication requirement. Run uvicorn with `--host 127.0.0.1` so only the proxy can reach it, point your proxy at `localhost:8000`, and update `CORS_ORIGINS` to match your domain.

Scene Atlas reads the client IP from `X-Forwarded-For` on connections from `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`, which fits a proxy on the same machine); see [Client IP addresses and rate limits](/deploy/server#client-ip-addresses-and-rate-limits). The commands on this page pass `--no-proxy-headers` so that uvicorn leaves those headers to the app; otherwise uvicorn applies its own trust list, which ignores `.env`.

## Updating

```bash
cd /opt/scene-atlas
git fetch --tags
git checkout v<version>      # the new release
uv sync --extra cpu    # or whichever extra you use
cd frontend && npm ci && npm run build && cd ..
sudo systemctl restart scene-atlas
```

Database migrations run automatically on startup.

## GPU Acceleration

```bash
# Set the device explicitly
INFERENCE_DEVICE=cuda uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
```

The automatic provider chain is: CUDA, DirectML, CoreML, CPU.

## Starting Over With an Empty Library

This deletes your library. Stop the server, then delete both `APP_DATA_DIR` (default `data/`: database, search index, thumbnails) and `IMAGE_LIBRARY_DIR` (default `images/`: stored files and backups). Both are recreated on the next start.

Delete them together: stored files are named by their content and can't be used without the database. Check first that neither setting points at a folder holding anything else, such as your own map collection.
