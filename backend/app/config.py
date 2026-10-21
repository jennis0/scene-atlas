"""Application configuration management."""

import logging
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend import __version__

_REPO_ROOT = Path(__file__).parent.parent.parent
_LEGACY_LIBRARY_DIR = _REPO_ROOT / "images"


def default_images_dir(data_dir: Path) -> Path:
    """Where originals go when SCENE_ATLAS_IMAGES_DIR isn't set: beside the data, so
    setting SCENE_ATLAS_DATA_DIR alone keeps a whole library in one place.

    Libraries made before this default kept their originals in ``<repo>/images``. A data
    folder that already has a database but no ``images`` folder is one of those, so it
    keeps using the old location (with a warning) rather than losing its originals.
    """
    library = data_dir / "images"
    if not library.exists() and (data_dir / "battlemap.db").exists():
        logging.getLogger(__name__).warning(
            "Using the image library at %s. Set SCENE_ATLAS_IMAGES_DIR to keep using it, or "
            "move it to %s",
            _LEGACY_LIBRARY_DIR,
            library,
        )
        return _LEGACY_LIBRARY_DIR
    return library


class Settings(BaseSettings):
    """Application settings. Each field is read from SCENE_ATLAS_<FIELD>, e.g. debug from
    SCENE_ATLAS_DEBUG (ADR-027)."""

    model_config = SettingsConfigDict(
        env_prefix="SCENE_ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Scene Atlas"
    app_version: str = __version__
    debug: bool = False

    # Deployment mode: 'app' when running as Electron desktop sidecar,
    # 'server' when running standalone via uvicorn.  Set via SCENE_ATLAS_APP_MODE.
    app_mode: Literal["app", "server"] = "server"

    # Server mode: ask GitHub once a day whether a newer release is out, to show in
    # Settings (services/update_check.py). False makes no request at all. The desktop
    # app ignores it; Electron checks for updates itself.
    check_for_updates: bool = True

    # Storage roots: Search data (SCENE_ATLAS_DATA_DIR) and Imported images
    # (SCENE_ATLAS_IMAGES_DIR). With neither set (development), they're data/ and images/
    # in the checkout; with only the data folder set, the images go inside it
    # (default_images_dir).
    data_dir: Path = _REPO_ROOT / "data"
    images_dir: Path = _LEGACY_LIBRARY_DIR
    # The linked library (SCENE_ATLAS_LINKED_LIBRARY_DIR): the user's own maps, read where
    # they are and never written. Optional, and it need not exist (design/library-setup.md).
    linked_library_dir: Path | None = None

    # Whether to validate that roots exist on startup.
    # Set to True in production entry points (entry.py).  False by default so
    # that tests and dev runs don't require pre-created directories.
    validate_roots: bool = False

    # Vector DB
    vector_size: int = 512
    inference_device: str = "auto"

    # Service constants
    clip_text_cache_max: int = 256
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
    # Most files a local import (desktop app, design/local-ingest.md) may contain. Higher:
    # the browser and the upload protocol, which the cap above protects, aren't involved.
    max_local_import_items: int = 250_000
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
    api_host: str = "0.0.0.0"  # noqa: S104  # nosec B104
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

    @field_validator("linked_library_dir", mode="before")
    @classmethod
    def _empty_linked_dir_is_none(cls, value):
        # SCENE_ATLAS_LINKED_LIBRARY_DIR= (e.g. an unset compose variable) means no folder.
        return None if isinstance(value, str) and not value.strip() else value

    # Paths derived from the two roots. They are not fields, so env vars such as
    # SCENE_ATLAS_DATABASE_URL cannot set them. Each is computed on first access and cached;
    # tests may assign them to redirect storage.
    @cached_property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'battlemap.db'}"

    @cached_property
    def store_thumbnails_dir(self) -> Path:
        return self.data_dir / "store" / "thumbnails"

    @cached_property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @cached_property
    def vector_db_path(self) -> Path:
        return self.data_dir / "lancedb"

    @cached_property
    def store_images_dir(self) -> Path:
        return self.images_dir

    @cached_property
    def backups_dir(self) -> Path:
        return self.images_dir / "backups"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if "data_dir" in self.model_fields_set and "images_dir" not in (self.model_fields_set):
            self.images_dir = default_images_dir(self.data_dir)

        # Validate roots exist if requested (set True in production entry points)
        if self.validate_roots:
            if not self.data_dir.exists():
                raise ValueError(
                    f"SCENE_ATLAS_DATA_DIR does not exist: {self.data_dir}. "
                    "Create it before starting the backend."
                )
            if not self.images_dir.exists():
                raise ValueError(
                    f"SCENE_ATLAS_IMAGES_DIR does not exist: {self.images_dir}. "
                    "Create it before starting the backend."
                )

        # Create expected subdirectories within the roots (not the roots themselves).
        self.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.vector_db_path.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
