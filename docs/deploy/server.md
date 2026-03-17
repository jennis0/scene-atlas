# Docker Server

Run Scene Atlas as a self-hosted web server using Docker. A single container serves both the API and the web UI on one port.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- **GPU only:** [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/joe-ennis/scene-atlas.git
cd scene-atlas

# Create your image directory (or use an existing one)
mkdir -p images

# Start with CPU inference
docker compose --profile cpu up -d
```

Open `http://localhost:8000` in your browser.

### With GPU

```bash
docker compose --profile gpu up -d
```

The GPU profile sets `INFERENCE_DEVICE=cuda` and reserves one NVIDIA GPU.

## Configuration

Create a `.env` file in the project root to customise settings:

```bash
# Port for the web UI and API
PORT=8000

# Path to your image library on the host
IMAGE_DIR=./images

# CORS origins (set to your domain if behind a reverse proxy)
CORS_ORIGINS=["http://localhost:8000"]

# AI model: clip-vit-b-32 (small), siglip2-base (medium), siglip2-so400m (large)
EMBEDDING_MODEL=clip-vit-b-32

# Enable debug logging
DEBUG=false
```

See the [Configuration Reference](/deploy/configuration) for all available settings.

## Volumes

| Volume | Type | Path in container | Purpose |
|--------|------|-------------------|---------|
| `scene-atlas-data` | Named | `/app/data` | Database, vector index, thumbnails, backups |
| `images` | Bind mount | `/app/images` | Your image library (read by the app) |

::: warning
The named volume `scene-atlas-data` contains your database and search index. Back it up regularly, or rely on Scene Atlas's built-in automated backups.
:::

## Reverse Proxy

Scene Atlas serves everything on a single port, so reverse proxy setup is straightforward.

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name atlas.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    client_max_body_size 2G;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Caddy

```
atlas.example.com {
    reverse_proxy localhost:8000
}
```

After configuring your proxy, update `CORS_ORIGINS` to match your domain:

```bash
CORS_ORIGINS=["https://atlas.example.com"]
```

## Authentication

Set `AUTH_TOKEN` to require a bearer token for all API requests:

```bash
AUTH_TOKEN=your-secret-token-here
```

When set, all requests must include `Authorization: Bearer your-secret-token-here`. The web UI prompts for the token on first visit.

## Backups

Scene Atlas runs automated daily backups with a rotation policy:
- **7 daily backups** retained
- **4 weekly backups** retained

Backups include the SQLite database and LanceDB vector storage. They're stored inside the `scene-atlas-data` volume at `/app/data/backups/`.

To restore from a backup, stop the container, copy the backup database into the data volume, and restart. Alembic migrations are applied automatically on startup if the schema has changed.

## Updating

```bash
# Pull the latest image and recreate
docker compose --profile cpu pull
docker compose --profile cpu up -d
```

Your data volume and images are preserved across updates.

## Troubleshooting

**Container won't start:** Check logs with `docker compose logs -f`. Common issues: port conflict, missing image directory, or GPU driver mismatch.

**Slow AI inference:** If using the medium or large model without a GPU, inference will be slow. Switch to the small model or enable GPU acceleration.

**Large uploads failing:** Ensure your reverse proxy allows large request bodies. The default max import size is 2 GB — Nginx's `client_max_body_size` must match or exceed this.
