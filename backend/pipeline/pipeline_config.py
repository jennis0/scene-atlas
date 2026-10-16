"""PipelineConfig — per-pipeline configuration for ingestion jobs.

This dataclass carries all tuning parameters that vary between pipeline runs
(feature flags, thresholds, batch sizes).  It replaces direct reads of
``settings.*`` inside pipeline functions, enabling future per-import overrides
without touching global state.

Usage in pipeline entry points:

    from backend.pipeline.pipeline_config import PipelineConfig, load_pipeline_config

    # Automatically read from DB:
    cfg = load_pipeline_config()

    # Or construct from an already-fetched AppSettings:
    from backend.app.services.app_settings import get_settings
    cfg = PipelineConfig.from_app_settings(get_settings(db))
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PipelineConfig:
    """Immutable configuration snapshot for a single pipeline run."""

    # Grid detection
    enable_image_grid_detection: bool = True
    grid_analysis_max_dim: int = 0  # 0 = full resolution

    # Color extraction
    num_dominant_colors: int = 5
    color_clustering_samples: int = 5000
    color_kmeans_n_init: int = 3

    # Ingestion performance
    ingestion_batch_size: int = 16
    max_concurrent_prepare: int = 4

    # Import processing
    use_webp: bool = False

    @property
    def grid_max_dim(self) -> int | None:
        """``grid_analysis_max_dim`` for the detector: None means full resolution."""
        return self.grid_analysis_max_dim or None

    @classmethod
    def from_app_settings(cls, s) -> PipelineConfig:
        """Create a PipelineConfig from an AppSettings instance."""
        return cls(
            enable_image_grid_detection=s.enable_image_grid_detection,
            grid_analysis_max_dim=s.grid_analysis_max_dim,
            num_dominant_colors=s.num_dominant_colors,
            color_clustering_samples=s.color_clustering_samples,
            color_kmeans_n_init=s.color_kmeans_n_init,
            ingestion_batch_size=s.ingestion_batch_size,
            max_concurrent_prepare=s.max_concurrent_prepare,
            use_webp=s.convert_to_webp,
        )


def load_pipeline_config() -> PipelineConfig:
    """Load a PipelineConfig by reading AppSettings from the database.

    Creates its own short-lived DB session.  Suitable for calling at the
    start of background pipeline jobs that don't already hold a session.
    """
    from backend.app.config import settings
    from backend.app.models.database import get_engine, get_session_local
    from backend.app.services.app_settings import get_settings as get_app_settings

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        app_settings = get_app_settings(db)
        return PipelineConfig.from_app_settings(app_settings)
    finally:
        db.close()
