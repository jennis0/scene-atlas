# Standalone Server

Run Scene Atlas directly on your machine without Docker. This is useful when Docker is unavailable or when you want more control over the runtime environment.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) for dependency management
- **Node.js 20+** with npm (for building the frontend)

## Installation

```bash
# Clone the repository
git clone https://github.com/joe-ennis/scene-atlas.git
cd scene-atlas

# Install Python dependencies
uv sync

# Build the frontend
cd frontend && npm ci && npm run build && cd ..

# Download the AI model
uv run python scripts/models/setup_models.py
```

## Running

```bash
# Start the server (serves both API and built frontend)
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

### Configuration

Set environment variables or create a `.env` file in the project root:

```bash
APP_DATA_DIR=./data
IMAGE_LIBRARY_DIR=/path/to/your/images
CORS_ORIGINS=["http://localhost:8000"]
```

See the [Configuration Reference](/deploy/configuration) for all available settings.

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
Environment=IMAGE_LIBRARY_DIR=/mnt/images
ExecStart=/opt/scene-atlas/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now scene-atlas
```

## Reverse Proxy

The same reverse proxy configurations from the [Docker Server guide](/deploy/server#reverse-proxy) apply here. Point your proxy at `localhost:8000` and update `CORS_ORIGINS` to match your domain.

## Updating

```bash
cd /opt/scene-atlas
git pull
uv sync
cd frontend && npm ci && npm run build && cd ..
sudo systemctl restart scene-atlas
```

Alembic database migrations run automatically on startup.

## GPU Acceleration

To use GPU acceleration with a standalone install:

```bash
# Install with CUDA support
uv sync --extra cuda

# Or set the device explicitly
INFERENCE_DEVICE=cuda uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

The automatic provider chain applies: CUDA → DirectML → CoreML → CPU.
