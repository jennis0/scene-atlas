"""Request and response models for the imports API (ADR-018, design/ingest-redesign.md §7)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ImageType = Literal["battlemap", "scene"]
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


class ImportGroupSummary(BaseModel):
    id: int
    author: str | None
    group_name: str
    image_group_id: int | None
    merged_into_existing: bool
    sort_order: int
    counts: ImportCounts


class ImportJobSummary(BaseModel):
    id: str
    label: str | None
    status: JobStatus
    default_image_type: ImageType
    planned: bool
    dismissed: bool
    upload_interrupted: bool  # derived: waiting on bytes that stopped arriving
    counts: ImportCounts
    group_count: int
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None
    last_upload_at: datetime | None


class ImportJobDetail(ImportJobSummary):
    groups: list[ImportGroupSummary]


class QueueStatus(BaseModel):
    running: bool
    system_paused: bool
    reason: str | None
    current_job_id: str | None


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


class ArchiveResult(BaseModel):
    name: str
    created: int
    skipped: int
    failed: int


# Items and actions


class ImportItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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


class ImportItemPage(BaseModel):
    items: list[ImportItemOut]
    next_after: int | None  # pass as ?after= for the next page


class ItemActionRequest(BaseModel):
    item_ids: list[int] | None = Field(None, max_length=MAX_ACTION_ITEMS)


class ActionResult(BaseModel):
    affected: int
    status: str
