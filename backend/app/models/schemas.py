"""Pydantic schemas for API request/response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TagBase(BaseModel):
    """Base tag schema."""

    category: str
    value: str
    confidence: float = 1.0
    source: str = "manual"


class TagCreate(TagBase):
    """Tag creation schema."""

    pass


class TagResponse(TagBase):
    """Tag response schema."""

    id: int
    image_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ColorBase(BaseModel):
    """Base color schema."""

    color_hex: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    percentage: float | None = None
    color_order: int | None = None


class ColorCreate(ColorBase):
    """Color creation schema."""

    pass


class ColorResponse(ColorBase):
    """Color response schema."""

    id: int
    image_id: int

    model_config = ConfigDict(from_attributes=True)


class ImageBase(BaseModel):
    """Base image schema."""

    filename: str
    storage_key: str
    name: str | None = None
    author: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    gridded: bool | None = None
    grid_width: int | None = None
    grid_height: int | None = None
    grid_type: str | None = None
    grid_confidence: float | None = None
    subgroup: str | None = None
    content_hash: str | None = None
    media_type: str | None = "image"
    image_type: str | None = "battlemap"


class ImageCreate(ImageBase):
    """Image creation schema."""

    tags: list[TagCreate] = []
    colors: list[ColorCreate] = []


class ImageResponse(ImageBase):
    """Image response schema."""

    id: int
    group_id: int | None = None
    group_name: str | None = None
    group_image_count: int | None = None
    thumbnail_key: str | None = None
    created_at: datetime
    updated_at: datetime
    tags: list[TagResponse] = []
    colors: list[ColorResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ImageSearchRequest(BaseModel):
    """Image search request schema."""

    text: str | None = None
    semantic: str | None = None
    tags: list[str] = []  # Format: ["category:value", "season:winter"]
    exclude_tags: list[str] = []
    author: str | None = None
    colors: list[str] = []  # Hex colors
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class ImageSearchResponse(BaseModel):
    """Image search response schema."""

    total: int
    limit: int
    offset: int
    images: list[ImageResponse]
    scores: dict[int, float] | None = None  # image_id -> semantic score


class GroupBase(BaseModel):
    """Base group schema."""

    base_name: str
    author: str | None = None


class GroupResponse(GroupBase):
    """Group response schema."""

    id: int
    primary_image_id: int | None = None
    created_at: datetime
    image_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class GroupDetailResponse(GroupBase):
    """Group with full image list."""

    id: int
    primary_image_id: int | None = None
    images: list[ImageResponse] = []

    model_config = ConfigDict(from_attributes=True)


class GroupPickerItem(BaseModel):
    """Lightweight group for group picker/merge results."""

    id: int
    base_name: str
    author: str | None = None
    primary_image_id: int | None = None
    image_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class GroupPickerResponse(BaseModel):
    """Response for group picker search."""

    groups: list["GroupPickerItem"]
    total: int


class GroupSearchResult(BaseModel):
    """Single group result for group search endpoint."""

    group_id: int
    base_name: str
    author: str | None = None
    hero_image: "ImageResponse"
    mosaic_images: list["ImageResponse"]
    total_scenes: int
    matching_scenes: int
    best_score: float | None = None
    all_image_ids: list[int] | None = None

    model_config = ConfigDict(from_attributes=True)


class GroupSearchResponse(BaseModel):
    """Response for group search endpoint (paginated)."""

    total_groups: int
    limit: int
    offset: int
    groups: list["GroupSearchResult"]


class GroupMergeRequest(BaseModel):
    """Request to merge source group into a target group."""

    target_group_id: int


class GroupMergeResponse(BaseModel):
    """Result of a merge operation."""

    target_group_id: int
    target_group_name: str
    images_moved: int
    source_group_deleted: bool


class MoveImagesRequest(BaseModel):
    """Move specific images from one group to another."""

    target_group_id: int
    image_ids: list[int]


class MoveImagesResponse(BaseModel):
    """Result of moving images between groups."""

    source_group_id: int
    target_group_id: int
    images_moved: int
    source_group_deleted: bool


class ImageEditPayload(BaseModel):
    """Per-image edit data sent from the edit dialog."""

    id: int
    name: str | None = None
    tags: list[TagBase] = []
    gridded: bool | None = None
    grid_width: int | None = None
    grid_height: int | None = None
    grid_type: str | None = None
    subgroup: str | None = None
    image_type: str | None = None


class NewGroupPayload(BaseModel):
    """A split-off group to create during a group edit."""

    base_name: str
    author: str | None = None
    image_ids: list[int]


class GroupEditRequest(BaseModel):
    """Full edit payload for a group."""

    base_name: str
    author: str | None = None
    images: list[ImageEditPayload]  # images to keep (with metadata updates)
    new_groups: list[NewGroupPayload] = []  # split-off groups; their images are moved, not deleted


class GroupEditResponse(BaseModel):
    """Result of a group edit."""

    id: int
    new_group_ids: list[int] = []
    deleted_image_ids: list[int] = []


class TagCategoryBase(BaseModel):
    """Base tag category schema."""

    name: str
    description: str | None = None
    common_values: str | None = None  # JSON string
    color: str | None = None  # Tailwind color preset name
    icon: str | None = None  # Lucide icon name, e.g. "leaf"
    display_order: int = 0


class TagCategoryCreate(BaseModel):
    """Schema for creating a new tag category."""

    name: str
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    display_order: int = 0


class TagCategoryUpdate(BaseModel):
    """Schema for updating a tag category (all fields optional)."""

    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    display_order: int | None = None


class TagValueUpdate(BaseModel):
    """Schema for renaming a tag value."""

    new_value: str


class TagCategoryResponse(TagCategoryBase):
    """Tag category response schema."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── App Settings ──────────────────────────────────────────────────────────────


class AppSettings(BaseModel):
    """DB-backed application settings (feature flags and tuning parameters).

    All defaults match the values previously held in config.py so that existing
    deployments behave identically until a user changes a setting.
    """

    # Grid detection (image analysis)
    enable_image_grid_detection: bool = True
    grid_min_cell_px: int = 32
    grid_max_cell_px: int = 320
    grid_detection_max_dim: int = 8_000
    grid_presence_threshold: float = 0.20
    grid_size_threshold: float = 0.15
    grid_period_ratio_threshold: float = 0.98
    grid_hex_rot_conf: float = 0.20

    # Color extraction
    num_dominant_colors: int = 5
    color_distance_threshold: float = 0.35
    color_clustering_samples: int = 5000
    color_kmeans_n_init: int = 3

    # Ingestion performance
    ingestion_batch_size: int = 16
    max_concurrent_prepare: int = 8
    max_concurrent_heavy_requests: int = 4

    # Import limits
    max_import_file_size: int = 2000 * 1024 * 1024
    max_video_file_size: int = 2000 * 1024 * 1024
    max_import_files: int = 1000
    max_import_total_size: int = 2048 * 1024 * 1024

    # Job runner (take effect on next restart)
    max_job_workers: int = 2
    scheduler_enabled: bool = True

    # Import processing
    convert_to_webp: bool = False
    webp_lossless: bool = True
    webp_quality: int = Field(95, ge=0, le=100)

    # Model selection (managed via POST /api/v1/models/active — not in AppSettingsPatch)
    active_model: str = ""  # "" = auto-detect at startup; "small"|"medium"|"large" once set


class AppSettingsPatch(BaseModel):
    """Partial update for app settings — only include fields you want to change."""

    enable_image_grid_detection: bool | None = None
    grid_min_cell_px: int | None = None
    grid_max_cell_px: int | None = None
    grid_detection_max_dim: int | None = None
    grid_presence_threshold: float | None = None
    grid_size_threshold: float | None = None
    grid_period_ratio_threshold: float | None = None
    grid_hex_rot_conf: float | None = None
    num_dominant_colors: int | None = None
    color_distance_threshold: float | None = None
    color_clustering_samples: int | None = None
    color_kmeans_n_init: int | None = None
    ingestion_batch_size: int | None = None
    max_concurrent_prepare: int | None = None
    max_concurrent_heavy_requests: int | None = None
    max_import_file_size: int | None = None
    max_video_file_size: int | None = None
    max_import_files: int | None = None
    max_import_total_size: int | None = None
    max_job_workers: int | None = None
    scheduler_enabled: bool | None = None
    convert_to_webp: bool | None = None
    webp_lossless: bool | None = None
    webp_quality: int | None = Field(None, ge=0, le=100)
