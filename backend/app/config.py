"""Application configuration management."""

from pathlib import Path

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
            p = Path(url[len("sqlite:///"):])
            return p if p.is_absolute() else self.base_dir / p
        raise ValueError(f"Cannot derive db_path from non-SQLite URL: {url}")

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
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

    # Color Extraction & Search
    num_dominant_colors: int = 5
    color_distance_threshold: float = 0.35  # HSL cylindrical distance for proximity search
    color_clustering_samples: int = 5000  # Pixels to sample for k-means
    color_kmeans_n_init: int = (
        3  # K-means random initializations (3 is sufficient for color extraction)
    )

    # Ingestion Performance
    ingestion_batch_size: int = 16  # Images per batch for CLIP and DB operations
    max_concurrent_prepare: int = 8  # Concurrent prepare_single_image tasks

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Prefect
    prefect_api_url: str = "http://localhost:4200/api"
    prefect_work_pool: str = "battlemap-pool"
    analyse_deployment: str = "analyse-deployment"
    analyse_flow: str = "analyse_upload"
    process_deployment: str = "import-deployment"
    process_flow: str = "process_import_group"
    # Single-flow path for multi-group imports — loads CLIP once for all groups
    process_job_deployment: str = "import-job-deployment"
    process_job_flow: str = "process_import_job"
    retag_deployment: str = "retag-all-images-deployment"
    retag_flow: str = "retag_all_images"

    # Import limits
    staging_dir: Path = data_dir / "staging"
    max_import_file_size: int = 200 * 1024 * 1024  # 50MB per image file
    max_video_file_size: int = 200 * 1024 * 1024  # 200MB per video file
    max_import_files: int = 1000  # Max images per import
    max_import_total_size: int = 2048 * 1024 * 1024  # 500MB total

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_images_dir.mkdir(parents=True, exist_ok=True)
        self.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
