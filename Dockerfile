# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:24-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN NODE_OPTIONS="--max-old-space-size=512" npm ci --prefer-offline

COPY frontend/ ./
RUN npm run build


# ── Stage 2: Backend runtime ─────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

# Build arg: which onnxruntime extra to install (cpu, gpu, gpu-directml)
ARG EXTRA=cpu
# The app runs as this unprivileged user. It must be able to write the IMAGE_DIR
# bind mount, so match it to the host owner of that directory (docker-compose
# passes APP_UID/APP_GID through from .env).
ARG APP_UID=1000
ARG APP_GID=1000

# System dependencies for OpenCV headless, Pillow, and general build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python dependencies (leverage Docker layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra "${EXTRA}" --no-dev --no-install-project

# Copy backend source, scripts, and alembic config
COPY backend/ backend/
COPY scripts/ scripts/
COPY alembic.ini ./

# Install the project itself (editable-style so backend package is importable)
RUN uv sync --frozen --extra "${EXTRA}" --no-dev

# Copy built frontend into static serving location
COPY --from=frontend-build /build/frontend/dist/ /app/frontend/dist/

# Mount points for the data volume and image library. A fresh named volume copies
# this ownership; the image bind mount keeps its host ownership (see APP_UID).
RUN mkdir -p /app/data /app/images && chown app:app /app/data /app/images

# Run the venv's executables directly: `uv run` would try to re-sync the root-owned venv.
ENV PATH="/app/.venv/bin:${PATH}"

USER app

EXPOSE 8000

# Proxy headers are handled by the app, trusting FORWARDED_ALLOW_IPS only.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
