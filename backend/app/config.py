"""Application configuration management."""

import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Application
    app_name: str = "Scene Atlas"
    app_version: str = "0.1.0"
    debug: bool = False

    # Deployment mode: 'app' when running as Electron desktop sidecar,
    # 'server' when running standalone via uvicorn.  Set via APP_MODE env var.
    app_mode: Literal["app", "server"] = "server"

    # Storage roots — set via APP_DATA_DIR and IMAGE_LIBRARY_DIR env vars
    app_data_dir: Path = Path(__file__).parent.parent.parent / "data"
    image_library_dir: Path = Path(__file__).parent.parent.parent / "images"

    # Whether to validate that roots exist on startup.
    # Set to True in production entry points (entry.py).  False by default so
    # that tests and dev runs don't require pre-created directories.
    validate_roots: bool = False

    # Vector DB
    vector_size: int = 512
    inference_device: str = "auto"

    # Service constants
    clip_text_cache_max: int = 256
    color_cache_ttl_seconds: float = 60.0
    job_retention_seconds: int = 3600

    # Image Processing
    thumbnail_sizes: list[tuple[int, int]] = [(150, 150), (400, 400), (800, 800)]
    # Largest image (in pixels) Pillow will decode; beyond this it's treated as a
    # decompression bomb. Pillow's default (~89.5 Mpx) rejects ~2% of real battlemap
    # libraries; the largest observed maps are ~760 Mpx (~1.7 GB RSS to process).
    max_image_pixels: int = 1_000_000_000
    # JPEGs above this many pixels are decoded at reduced scale (libjpeg DCT
    # scaling) instead of in full, and skip the pixel-hash duplicate check (the
    # byte hash still applies). ~400 MB peak at the limit instead of gigabytes.
    pixel_hash_max_pixels: int = 100_000_000
    # Memory reserved across concurrent image preparation; None = automatic
    # (half of RAM beyond a 2 GiB reserve).
    ingest_memory_budget_mb: int | None = None
    # Most files one import job may contain (across all manifest chunks).
    max_import_items: int = 50_000
    # Start the ingest worker with the app. Tests turn this off and drive the
    # worker synchronously with drain().
    ingest_worker_enabled: bool = True
    supported_formats: list[str] = [".jpg", ".jpeg", ".png", ".webp"]
    supported_video_formats: list[str] = [".mp4", ".webm"]

    # Rate limiting
    rate_limit_expensive: str = "2/minute"
    rate_limit_destructive: str = "1/minute"
    rate_limit_enabled: bool = True

    # API
    # Only read by `python -m backend.app.main` (dev/E2E). Electron forces 127.0.0.1 and
    # Docker/uvicorn pass --host explicitly; see design/security.md (accepted risks).
    api_host: str = "0.0.0.0"  # nosec B104
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    # Proxies whose X-Forwarded-For / X-Forwarded-Proto are believed: comma-separated
    # IPs or CIDR networks, or "*". Same name and format as uvicorn's option.
    forwarded_allow_ips: str = "127.0.0.1,::1"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ]

    # Paths derived from the two roots. They are not fields, so env vars such as
    # DATABASE_URL cannot set them. Each is computed on first access and cached;
    # tests may assign them to redirect storage.
    @cached_property
    def database_url(self) -> str:
        return f"sqlite:///{self.app_data_dir / 'battlemap.db'}"

    @cached_property
    def store_thumbnails_dir(self) -> Path:
        return self.app_data_dir / "store" / "thumbnails"

    @cached_property
    def staging_dir(self) -> Path:
        return self.app_data_dir / "staging"

    @cached_property
    def vector_db_path(self) -> Path:
        return self.app_data_dir / "lancedb"

    @cached_property
    def store_images_dir(self) -> Path:
        return self.image_library_dir

    @cached_property
    def backups_dir(self) -> Path:
        return self.image_library_dir / "backups"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Migration aid: warn if the old CLIP_DEVICE env var is set
        if os.environ.get("CLIP_DEVICE"):
            logging.getLogger(__name__).warning(
                "CLIP_DEVICE env var is deprecated and ignored. "
                "Use INFERENCE_DEVICE instead (auto/cpu/cuda/directml/coreml)."
            )

        # Validate roots exist if requested (set True in production entry points)
        if self.validate_roots:
            if not self.app_data_dir.exists():
                raise ValueError(
                    f"APP_DATA_DIR does not exist: {self.app_data_dir}. "
                    "Create it before starting the backend."
                )
            if not self.image_library_dir.exists():
                raise ValueError(
                    f"IMAGE_LIBRARY_DIR does not exist: {self.image_library_dir}. "
                    "Create it before starting the backend."
                )

        # Create expected subdirectories within the roots (not the roots themselves).
        self.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.vector_db_path.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
