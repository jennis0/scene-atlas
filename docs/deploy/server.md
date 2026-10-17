# Docker Server

Run Scene Atlas as a self-hosted web server. A single container serves the API and web UI on one port.

::: danger No built-in authentication
Server mode has no login and no access control: anyone who can reach the port can browse, upload, edit, and delete your library. Expose it only behind a reverse proxy that authenticates users (for example HTTP basic auth, a forward-auth service such as Authelia or authentik, or an OAuth proxy such as oauth2-proxy). Never expose it directly to the internet.
:::

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

# Proxies trusted to report the client IP (see Reverse Proxy below)
FORWARDED_ALLOW_IPS=127.0.0.1,::1

# AI model size: small, medium, or large (optional; overrides the model chosen in the UI)
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
| `scene-atlas-data` | Named | `/app/data` | Database, vector index, thumbnails, logs |
| `IMAGE_DIR` | Bind mount | `/app/images` | Managed image storage and backups |

::: warning
The named volume `scene-atlas-data` contains your database and search index. The built-in backups are written to the image bind mount, so back up `IMAGE_DIR` (or both) with your normal backup tooling.
:::

## Reverse Proxy

Scene Atlas serves everything on a single port, so proxy setup is straightforward. The proxy must also handle authentication (see the warning at the top of this page), and the container port should only be reachable by the proxy. `docker-compose.yml` publishes `${PORT}` on all interfaces; if the proxy runs on the same host, set `PORT=127.0.0.1:8000` in `.env` to bind to loopback only.

The examples below show TLS and forwarding only; add an authentication layer before using them.

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name atlas.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    client_max_body_size 2G;

    location / {
        # Authentication is required; basic auth shown here. Replace with
        # auth_request (forward-auth) or an OAuth proxy if preferred.
        auth_basic           "Scene Atlas";
        auth_basic_user_file /etc/nginx/scene-atlas.htpasswd;

        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;  # overwrite, do not append
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Caddy

```
atlas.example.com {
    basic_auth {
        # caddy hash-password generates the hash
        alice <bcrypt-hash>
    }
    reverse_proxy localhost:8000
}
```

After configuring your proxy, update `CORS_ORIGINS`:

```bash
CORS_ORIGINS=["https://atlas.example.com"]
```

### Client IP addresses and rate limits

A few expensive and destructive endpoints are rate limited per client IP address. Behind a proxy, every request arrives from the proxy, so Scene Atlas takes the client address from the `X-Forwarded-For` header instead, but only on connections from an address listed in `FORWARDED_ALLOW_IPS`. From any other address the header is ignored, so clients can't fake it.

The default, `127.0.0.1,::1`, suits a proxy on the same machine as a [standalone](/deploy/standalone) install. In Docker, connections from a proxy on the host arrive from the Docker network's gateway, not from `127.0.0.1`, so set `FORWARDED_ALLOW_IPS` in `.env`:

```bash
# Proxy on the host: the gateway of the compose network
# (docker network inspect scene-atlas_default --format '{{(index .IPAM.Config 0).Gateway}}')
FORWARDED_ALLOW_IPS=172.18.0.1

# Proxy in another container on the same network: its address, or the network's subnet
FORWARDED_ALLOW_IPS=172.18.0.0/16
```

Entries are IP addresses or CIDR networks, comma-separated. If the proxy isn't listed, Scene Atlas still works, but all users share one rate-limit allowance. Use `*` (trust everyone) only if nothing but the proxy can reach the port.

## Authentication

Scene Atlas has no built-in authentication or user accounts. All access control must come from the reverse proxy in front of it. Each file in an import is a separate HTTP request, so proxy rate limits must allow a high request rate from authenticated users.

## Backups

When the scheduler is enabled (the default), Scene Atlas backs up every 24 hours:
- The 7 most recent snapshots are kept
- Up to 4 older snapshots are kept, one per week

Each backup contains the SQLite database (`battlemap.db`) and a LanceDB vector index snapshot. They are written to `/app/images/backups/<timestamp>/`, i.e. `IMAGE_DIR/backups/` on the host.

To restore: stop the container, copy `battlemap.db` from a backup into the data volume as `/app/data/battlemap.db`, and restart. Schema migrations are applied automatically on startup.

## Updating

The image is built locally from the repository, so update by pulling the source and rebuilding:

```bash
git pull
docker compose --profile cpu up -d --build
```

Your data volume and images are preserved across updates.

## Troubleshooting

**Container won't start:** Check logs with `docker compose logs -f`. Common causes: port conflict, missing image directory, GPU driver mismatch.

**Slow processing:** The medium and large models are slow without a GPU. Switch to the small model or add GPU acceleration.

**Large uploads failing:** Your reverse proxy must allow large request bodies. Nginx needs `client_max_body_size 2G;` (or higher) to match Scene Atlas's default import limit.
