"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TagBase(BaseModel):
    """Base tag schema."""

    category: str
    value: str
    confidence: float = 1.0
    source: str = "manual"


class TagCreate(TagBase):
    """Tag creation schema."""


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
    grid_source: str | None = None
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


# Bulk image edits cover a whole import's All view in one request.
MAX_BULK_IMAGE_IDS = 20000
# A scope names groups, not images: an initial library import can plan ~10k groups.
MAX_SCOPE_GROUP_IDS = 20000


class BulkImageChanges(BaseModel):
    """Fields a bulk edit sets on every image. Only the fields sent are changed, and
    null is a value (e.g. ``subgroup: null`` clears it)."""

    image_type: Literal["battlemap", "scene"] | None = None
    gridded: bool | None = None
    grid_type: str | None = None
    grid_width: int | None = None
    grid_height: int | None = None
    subgroup: str | None = None


class TagRef(BaseModel):
    category: str
    value: str


class ImageScopeFilter(BaseModel):
    """Narrows an image scope. Only fields sent apply; ``subgroup: null`` means none set."""

    image_type: Literal["battlemap", "scene"] | None = None
    grid: Literal["square", "hex", "gridded", "gridless", "unknown"] | None = None
    subgroup: str | None = None
    tag: TagRef | None = None


class ImageScope(BaseModel):
    """The images of some groups, optionally filtered: resolved on the server."""

    group_ids: list[int] = Field(min_length=1, max_length=MAX_SCOPE_GROUP_IDS)
    filter: ImageScopeFilter = ImageScopeFilter()


class ScopeFacetCount(BaseModel):
    value: str | None
    count: int


class ImageScopeFacets(BaseModel):
    """How a scope's images break down: what the bulk panel shows and filters by."""

    total: int
    image_type: list[ScopeFacetCount]
    grid: list[ScopeFacetCount]
    subgroup: list[ScopeFacetCount]
    tags: list[ScopeFacetCount]  # value is "category:value"


class BulkImageEditRequest(BaseModel):
    """One change applied to many images, named by id or by a scope (exactly one)."""

    image_ids: list[int] | None = Field(default=None, min_length=1, max_length=MAX_BULK_IMAGE_IDS)
    scope: ImageScope | None = None
    changes: BulkImageChanges = BulkImageChanges()
    add_tags: list[TagCreate] = Field(default=[], max_length=50)

    @model_validator(mode="after")
    def _one_target(self) -> "BulkImageEditRequest":
        if (self.image_ids is None) == (self.scope is None):
            raise ValueError("send exactly one of image_ids and scope")
        return self


class BulkImageEditResponse(BaseModel):
    """What a bulk edit changed; ``undo_id`` reverts it (POST /images/bulk-restore)."""

    updated: int
    undo_id: str


class BulkImageRestoreRequest(BaseModel):
    undo_id: str


class BulkImageRestoreResponse(BaseModel):
    restored: int


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


# Caps for the batch group reads: summaries are a few hundred bytes each, details
# carry every image (~1.2 KB each), so clients page details in smaller batches.
MAX_GROUP_SUMMARY_IDS = 5000
MAX_GROUP_DETAIL_IDS = 100


class GroupSummariesRequest(BaseModel):
    """Group ids to summarise, in the order the client wants them back."""

    ids: list[int] = Field(min_length=1, max_length=MAX_GROUP_SUMMARY_IDS)


class GroupDetailsRequest(BaseModel):
    """Group ids to return in full, in the order the client wants them back."""

    ids: list[int] = Field(min_length=1, max_length=MAX_GROUP_DETAIL_IDS)


class GroupBulkUpdateRequest(BaseModel):
    """Set the author of many groups (and their images) at once."""

    ids: list[int] = Field(min_length=1, max_length=MAX_GROUP_SUMMARY_IDS)
    author: str | None = None


class GroupBulkUpdateResponse(BaseModel):
    updated: int


class GroupSummary(BaseModel):
    """A group without its image details: enough to list it and address its images."""

    id: int
    base_name: str
    author: str | None = None
    primary_image_id: int | None = None
    image_count: int = 0
    image_ids: list[int] = []


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


# App Settings


StoredFormatName = Literal["original", "webp", "jpeg", "png"]


class AppSettings(BaseModel):
    """DB-backed application settings (feature flags and tuning parameters).

    All defaults match the values previously held in config.py so that existing
    deployments behave identically until a user changes a setting.
    """

    # Grid detection (image analysis)
    enable_image_grid_detection: bool = True
    # Longest side analysed; 0 = full resolution (default). Lower is faster but misses
    # thin grid lines on high-resolution maps (design/grid-detection-v3.md).
    grid_analysis_max_dim: int = Field(default=0, ge=0)

    # Color extraction
    num_dominant_colors: int = 5
    # CIE76 delta E between a searched colour and an image's dominant colour.
    color_distance_threshold: float = Field(default=25.0, ge=0, le=100)
    color_clustering_samples: int = 5000
    color_kmeans_n_init: int = 3

    # Ingestion performance
    ingestion_batch_size: int = 16
    max_concurrent_prepare: int = 4
    max_concurrent_heavy_requests: int = 4

    # Import limits
    max_import_file_size: int = 2048 * 1024 * 1024
    max_video_file_size: int = 2048 * 1024 * 1024
    max_import_files: int = 1000
    max_import_total_size: int = 2048 * 1024 * 1024

    # Job runner (take effect on next restart)
    max_job_workers: int = 2
    scheduler_enabled: bool = True

    # Storage format for new imports (design/ingestion.md §10)
    stored_format: StoredFormatName = "original"
    stored_quality: int = Field(default=90, ge=1, le=100)  # lossy WebP and JPEG
    stored_lossless: bool = True  # lossless WebP for lossless sources (never for JPEGs)

    # Model selection (managed via POST /api/v1/models/active — not in AppSettingsPatch)
    active_model: str = ""  # "" = auto-detect at startup; "small"|"medium"|"large" once set


class AppSettingsPatch(BaseModel):
    """Partial update for app settings — only include fields you want to change."""

    enable_image_grid_detection: bool | None = None
    grid_analysis_max_dim: int | None = Field(None, ge=0)
    num_dominant_colors: int | None = None
    color_distance_threshold: float | None = Field(None, ge=0, le=100)
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
    stored_format: StoredFormatName | None = None
    stored_quality: int | None = Field(None, ge=1, le=100)
    stored_lossless: bool | None = None
