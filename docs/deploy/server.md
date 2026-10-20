# Docker Server

Run Scene Atlas as a self-hosted web server. A single container serves the API and web UI on one port.

::: danger No built-in authentication
Server mode has no login and no access control: anyone who can reach the port can browse, upload, edit, and delete your library. Expose it only behind a reverse proxy that authenticates users (for example HTTP basic auth, a forward-auth service such as Authelia or authentik, or an OAuth proxy such as oauth2-proxy). Never expose it directly to the internet.
:::

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- **GPU only:** [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

Each release publishes an image, `ghcr.io/jennis0/scene-atlas`, and the Compose file that runs it:

```bash
mkdir scene-atlas && cd scene-atlas
curl -fsSLO https://github.com/jennis0/scene-atlas/releases/latest/download/docker-compose.yml
curl -fsSL -o .env https://github.com/jennis0/scene-atlas/releases/latest/download/env.example
mkdir images

docker compose --profile cpu up -d
```

Open `http://localhost:8000` in your browser. The container runs as user and group 1000, which must own `images`; see [Container user](#configuration) if yours differ.

### With GPU

No GPU image is published, so the GPU profile builds one from the source. Check out the release you want to run:

```bash
git clone https://github.com/jennis0/scene-atlas.git
cd scene-atlas
git checkout v<version>   # the latest release, from https://github.com/jennis0/scene-atlas/releases
docker compose --profile gpu up -d
```

The GPU profile sets `INFERENCE_DEVICE=cuda` and reserves one NVIDIA GPU.

## Configuration

Settings go in a `.env` file next to `docker-compose.yml`:

```bash
# Port for the web UI and API
PORT=8000

# Host path for managed image storage (Scene Atlas writes its file structure here)
IMAGE_DIR=./images

# User and group the container runs as; must own IMAGE_DIR (run `id -u` / `id -g`)
APP_UID=1000
APP_GID=1000

# Release to run (e.g. 0.2.0); leave unset to follow the latest release
SCENE_ATLAS_VERSION=

# CORS origins (set to your domain if behind a reverse proxy)
CORS_ORIGINS=["http://localhost:8000"]

# Proxies trusted to report the client IP (see Reverse Proxy below)
FORWARDED_ALLOW_IPS=127.0.0.1,::1

# AI model size: small, medium, or large (optional; overrides the model chosen in the UI)
EMBEDDING_MODEL=small

# Enable debug logging
DEBUG=false

# Daily check for a newer release, shown in Settings (false: never contact GitHub)
CHECK_FOR_UPDATES=true
```

::: warning
`IMAGE_DIR` is where Scene Atlas stores imported images in its own file structure. Do not point it at your existing image collection. Import your images through the web UI instead.
:::

::: info Container user
The container runs as an unprivileged user (UID/GID `APP_UID`/`APP_GID`, default 1000), not root. Create `IMAGE_DIR` before the first start and make sure that user owns it, e.g. `mkdir -p images && sudo chown 1000:1000 images`; if Docker creates the directory itself it is owned by root and imports fail with a permission error. Set `APP_UID`/`APP_GID` before the first start: the data volume's files belong to that user, so changing it later means `chown -R` on the volume as well as `IMAGE_DIR`.

Installs created before this change ran as root, so their `scene-atlas-data` volume is root-owned. Start from a fresh volume (`docker compose down -v`, after taking a backup) or `chown -R` the volume and `IMAGE_DIR` to the new user.
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

Pull the new image and restart:

```bash
docker compose --profile cpu pull
docker compose --profile cpu up -d
```

Both need `--profile cpu`: without it, `docker compose pull` skips the service and nothing changes.

This follows the latest release unless `SCENE_ATLAS_VERSION` pins one; to move a pinned install, change it in `.env` first. Your data volume and images are kept, and the database is backed up before any schema change. Each release's notes say what changed, and a release can update `docker-compose.yml` too: download it again when its notes say so.

**GPU profile**, or a server built from a checkout: check out the new release's tag and rebuild.

```bash
git fetch --tags
git checkout v<version>   # the new release
docker compose --profile gpu up -d --build
```

Run releases rather than `main`: `main` holds unreleased changes, and a database upgraded by a newer schema can't go back to an older release.

## Troubleshooting

**Container won't start:** Check logs with `docker compose logs -f`. Common causes: port conflict, missing image directory, GPU driver mismatch.

**Slow processing:** The medium and large models are slow without a GPU. Switch to the small model or add GPU acceleration.

**Large uploads failing:** Your reverse proxy must allow large request bodies. Nginx needs `client_max_body_size 2G;` (or higher) to match Scene Atlas's default import limit.
