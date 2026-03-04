"""Application configuration management."""

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

    # Paths
    base_dir: Path = Path(__file__).parent.parent.parent
    data_dir: Path = base_dir / "data"
    store_images_dir: Path = data_dir / "store" / "images"  # Object store for images
    store_thumbnails_dir: Path = data_dir / "store" / "thumbnails"  # Object store for thumbnails
    config_dir: Path = base_dir / "config"

    # Database
    database_url: str = "sqlite:///./data/battlemap.db"

    @property
    def db_path(self) -> Path:
        """Path to the SQLite file, derived from database_url."""
        url = self.database_url
        if url.startswith("sqlite:///"):
            p = Path(url[len("sqlite:///") :])
            return p if p.is_absolute() else self.base_dir / p
        raise ValueError(f"Cannot derive db_path from non-SQLite URL: {url}")

    # Qdrant (embedded local mode)
    qdrant_path: Path = data_dir / "qdrant_local"
    qdrant_collection_name: str = "battlemap_images"
    qdrant_vector_size: int = 512  # CLIP ViT-B/32 projection_dim (common space for text & image)

    # CLIP Model
    # clip_model_name: str = "openai/clip-vit-base-patch32"
    clip_model_name: str = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    clip_device: str = "cpu"  # or "cuda" if GPU available

    # Image Processing
    thumbnail_sizes: list[tuple[int, int]] = [
        (150, 150),  # Small thumbnail
        (400, 400),  # Medium thumbnail
        (800, 800),  # Large thumbnail
    ]
    max_image_size: int = 10 * 1024 * 1024  # 10MB
    supported_formats: list[str] = [".jpg", ".jpeg", ".png", ".webp"]
    supported_video_formats: list[str] = [".mp4", ".webm"]

    @property
    def all_supported_formats(self) -> list[str]:
        return self.supported_formats + self.supported_video_formats

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ]
    # Auth — optional bearer token for server mode.
    # Leave unset (default) for Electron/dev backwards compatibility.
    # Generate with: uv run python -m backend.scripts.generate_token
    auth_token: str | None = None

    # Rate limiting — set rate_limit_enabled=False to disable in dev/local mode
    rate_limit_default: str = "60/minute"
    rate_limit_upload: str = "20/minute"
    rate_limit_expensive: str = "2/minute"  # rebuild-embeddings, export
    rate_limit_destructive: str = "1/minute"  # library purge
    rate_limit_enabled: bool = True

    # Import staging directory
    staging_dir: Path = data_dir / "staging"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Recompute derived paths when data_dir was overridden (e.g. via DATA_DIR env var
        # for desktop/sidecar mode). Class-level defaults are computed at definition time
        # from the original base_dir, so they won't reflect an overridden data_dir.
        _default_data = Path(__file__).parent.parent.parent / "data"
        if self.data_dir != _default_data:
            self.store_images_dir = self.data_dir / "store" / "images"
            self.store_thumbnails_dir = self.data_dir / "store" / "thumbnails"
            self.staging_dir = self.data_dir / "staging"
            self.qdrant_path = self.data_dir / "qdrant_local"
            self.database_url = f"sqlite:///{self.data_dir / 'battlemap.db'}"
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_images_dir.mkdir(parents=True, exist_ok=True)
        self.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
