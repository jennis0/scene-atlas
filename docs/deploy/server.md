# Docker Server

Run Scene Atlas as a self-hosted web server. A single container serves the API and web UI on one port.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- **GPU only:** [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

```bash
git clone https://github.com/jennis0/scene-atlas.git
cd scene-atlas

# CPU inference
docker compose --profile cpu up -d
```

Open `http://localhost:8000` in your browser.

### With GPU

```bash
docker compose --profile gpu up -d
```

The GPU profile sets `INFERENCE_DEVICE=cuda` and reserves one NVIDIA GPU.

## Configuration

Create a `.env` file in the project root:

```bash
# Port for the web UI and API
PORT=8000

# Host path for managed image storage (Scene Atlas writes its file structure here)
IMAGE_DIR=./images

# CORS origins (set to your domain if behind a reverse proxy)
CORS_ORIGINS=["http://localhost:8000"]

# AI model size: small, medium, or large
EMBEDDING_MODEL=small

# Enable debug logging
DEBUG=false
```

::: warning
`IMAGE_DIR` is where Scene Atlas stores imported images in its own file structure. Do not point it at your existing image collection. Import your images through the web UI instead.
:::

See the [Configuration Reference](/deploy/configuration) for all settings.

::: info Docker vs standalone variable names
In Docker, use `IMAGE_DIR` in your `.env` to set the host-side bind mount path. Inside the container, it's mapped to `IMAGE_LIBRARY_DIR=/app/images`. In standalone (non-Docker) deployments, use `IMAGE_LIBRARY_DIR` directly.
:::

## Volumes

| Volume | Type | Path in container | Purpose |
|--------|------|-------------------|---------|
| `scene-atlas-data` | Named | `/app/data` | Database, vector index, thumbnails, backups |
| `IMAGE_DIR` | Bind mount | `/app/images` | Managed image storage |

::: warning
The named volume `scene-atlas-data` contains your database and search index. Back it up regularly, or rely on Scene Atlas's built-in automated backups.
:::

## Reverse Proxy

Scene Atlas serves everything on a single port, so proxy setup is straightforward.

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

After configuring your proxy, update `CORS_ORIGINS`:

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

Scene Atlas runs automated daily backups:
- **7 daily** snapshots retained
- **4 weekly** snapshots retained

Backups include the SQLite database and LanceDB vector index. They're stored inside the `scene-atlas-data` volume at `/app/data/backups/`.

To restore: stop the container, copy the backup database into the data volume, and restart. Schema migrations are applied automatically on startup.

## Updating

```bash
docker compose --profile cpu pull
docker compose --profile cpu up -d
```

Your data volume and images are preserved across updates.

## Troubleshooting

**Container won't start:** Check logs with `docker compose logs -f`. Common causes: port conflict, missing image directory, GPU driver mismatch.

**Slow processing:** The medium and large models are slow without a GPU. Switch to the small model or add GPU acceleration.

**Large uploads failing:** Your reverse proxy must allow large request bodies. Nginx needs `client_max_body_size 2G;` (or higher) to match Scene Atlas's default import limit.
