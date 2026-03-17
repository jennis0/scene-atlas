# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:22-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN NODE_OPTIONS="--max-old-space-size=512" npm ci --prefer-offline

COPY frontend/ ./
RUN npm run build


# ── Stage 2: Backend runtime ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Build arg: which onnxruntime extra to install (cpu, gpu, gpu-directml)
ARG EXTRA=cpu

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

# Create data and image directories (will be overridden by volume mounts)
RUN mkdir -p /app/data /app/images

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
