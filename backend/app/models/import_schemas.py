"""Request and response models for the imports API (ADR-018, design/ingestion.md §7)."""

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# auto: the image-type head picks battlemap or scene, and sorts out tokens and other
# images (design/ingestion.md §5.6)
ImageType = Literal["battlemap", "scene", "auto"]
JobStatus = Literal["active", "paused", "completed", "cancelled"]

MAX_MANIFEST_CHUNK = 2000
MAX_HASH_CHUNK = 2000
MAX_ACTION_ITEMS = 10_000


# Summaries


class ImportCounts(BaseModel):
    """Item counts by state."""

    awaiting_bytes: int = 0
    ready: int = 0
    processing: int = 0
    done: int = 0
    duplicate: int = 0
    failed: int = 0
    skipped: int = 0
    total: int = 0
    sorted_out: int = 0  # of skipped: Auto set these aside and they can still be included


class ImportGroupSummary(BaseModel):
    id: int
    author: str | None
    group_name: str
    image_group_id: int | None
    merged_into_existing: bool
    sort_order: int
    counts: ImportCounts
    # An image this import added to the group, for a thumbnail in the report
    cover_image_id: int | None = None
    # The images this import added, by type (the report; 0 for groups=active)
    map_count: int = 0
    scene_count: int = 0


class ImportJobSummary(BaseModel):
    id: str
    label: str | None
    status: JobStatus
    default_image_type: ImageType
    planned: bool
    dismissed: bool
    upload_interrupted: bool  # derived: waiting on bytes that stopped arriving
    local: bool = False  # read from folders on this computer (design/local-ingest.md)
    waiting_for: list[str] = []  # derived: a local import's folders that are missing
    counts: ImportCounts
    group_count: int
    groups_done: int = 0  # groups with no open items (planned jobs)
    # Gallery groups the review editor can open: one of this import's groups that resolved
    # to it has an imported image, and none of them is still importing
    groups_reviewable: int = 0
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None
    last_upload_at: datetime | None


class ImportJobDetail(ImportJobSummary):
    groups: list[ImportGroupSummary]
    # The gallery groups counted by ``groups_reviewable``, in import order
    reviewable_group_ids: list[int] = []


class QueueStatus(BaseModel):
    running: bool
    system_paused: bool
    reason: str | None
    current_job_id: str | None
    # Rolling average time to import one file this session; None until measured
    # (design/import-progress.md §4)
    seconds_per_item: float | None = None


class ImportJobList(BaseModel):
    jobs: list[ImportJobSummary]
    queue: QueueStatus
    version: int


# Create, manifest, hashes


class CreateImportRequest(BaseModel):
    label: str | None = Field(None, max_length=200)
    default_image_type: ImageType = "battlemap"


class ManifestFile(BaseModel):
    client_ref: str | None = Field(None, max_length=200)
    relative_path: str = Field(..., min_length=1, max_length=1024)
    size: int | None = Field(None, ge=0)
    last_modified: int | None = None  # ms since epoch, as reported by the client
    image_type: ImageType | None = None


class ManifestRequest(BaseModel):
    files: list[ManifestFile] = Field(..., max_length=MAX_MANIFEST_CHUNK)


class ManifestItemResult(BaseModel):
    client_ref: str | None
    item_id: int
    relative_path: str
    state: str
    error_reason: str | None


class ManifestResponse(BaseModel):
    items: list[ManifestItemResult]
    ignored: int  # OS junk and repeated paths, dropped entirely


class HashEntry(BaseModel):
    item_id: int
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class HashRequest(BaseModel):
    items: list[HashEntry] = Field(..., max_length=MAX_HASH_CHUNK)


class HashResult(BaseModel):
    item_id: int
    state: str
    duplicate_of_image_id: int | None


class HashResponse(BaseModel):
    items: list[HashResult]


# Bytes


class ContentResult(BaseModel):
    item_id: int
    state: str
    error_reason: str | None
    duplicate_of_image_id: int | None


# Most roots (picked or dropped files and folders) one local-sources call may name.
MAX_LOCAL_ROOTS = 1000


class LocalSourcesRequest(BaseModel):
    paths: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        ..., min_length=1, max_length=MAX_LOCAL_ROOTS
    )


class LocalSourcesResult(BaseModel):
    created: int
    skipped: int
    failed: int
    ignored: int  # OS junk and paths already in the import


class ArchiveResult(BaseModel):
    name: str
    created: int
    skipped: int
    failed: int


# Items and actions


class ImportItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    import_group_id: int | None
    kind: str
    relative_path: str
    filename: str
    image_type: str
    size: int | None
    state: str
    attempts: int
    error_kind: str | None
    error_stage: str | None
    error_reason: str | None
    image_id: int | None
    duplicate_of_image_id: int | None
    duplicate_tier: str | None
    allow_duplicate: bool
    similar_to_image_id: int | None
    updated_at: datetime | None
    # Auto items: {group, probabilities, fell_back, head}
    classification: dict | None = None
    preview_key: str | None = Field(None, exclude=True)

    @field_validator("classification", mode="before")
    @classmethod
    def _parse_classification(cls, value):
        return json.loads(value) if isinstance(value, str) else value

    @computed_field
    @property
    def has_preview(self) -> bool:
        """Items Auto sorted out keep a preview: GET /imports/{job}/items/{id}/preview."""
        return self.preview_key is not None


class ImportItemPage(BaseModel):
    items: list[ImportItemOut]
    next_after: int | None  # pass as ?after= for the next page


class ItemActionRequest(BaseModel):
    item_ids: list[int] | None = Field(None, max_length=MAX_ACTION_ITEMS)


class IncludeRequest(BaseModel):
    item_ids: list[int] = Field(..., min_length=1, max_length=MAX_ACTION_ITEMS)


class IncludeResult(BaseModel):
    affected: int
    job_ids: list[str]


class SortedOutList(BaseModel):
    items: list[ImportItemOut]
    truncated: bool  # more than the limit; the rest are in each import's report


class SortedOutCounts(BaseModel):
    counts: dict[int, int]  # gallery group id → items Auto sorted out of it


class ActionResult(BaseModel):
    affected: int
    status: str


class DismissedResult(BaseModel):
    dismissed: int
