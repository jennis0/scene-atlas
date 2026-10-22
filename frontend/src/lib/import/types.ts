/**
 * Types for the imports API (ADR-018, design/ingestion.md §7).
 * Mirrors backend/app/models/import_schemas.py.
 */

/** auto: the image-type head picks battlemap or scene and sets aside tokens and other art */
export type ImageType = 'battlemap' | 'scene' | 'auto'

export type ItemState =
  'awaiting_bytes' | 'ready' | 'processing' | 'done' | 'duplicate' | 'failed' | 'skipped'

export type JobStatus = 'active' | 'paused' | 'completed' | 'cancelled'

export interface ImportCounts {
  awaiting_bytes: number
  ready: number
  processing: number
  done: number
  duplicate: number
  failed: number
  skipped: number
  total: number
  /** Of skipped: set aside by Auto and still includable (expired ones aren't counted) */
  sorted_out: number
}

export interface ImportGroupSummary {
  id: number
  author: string | null
  group_name: string
  image_group_id: number | null
  merged_into_existing: boolean
  sort_order: number
  counts: ImportCounts
  /** An image this import added to the group, for a thumbnail in the report */
  cover_image_id?: number | null
  /** The images this import added, by type (the report; 0 in the progress view) */
  map_count: number
  scene_count: number
}

export interface ImportJobSummary {
  id: string
  label: string | null
  status: JobStatus
  default_image_type: ImageType
  planned: boolean
  dismissed: boolean
  upload_interrupted: boolean
  /** Read from folders on this computer (desktop app); nothing to upload or resume. */
  local: boolean
  /** A scan of the linked folder: no Undo, and its report never opens by itself. */
  linked: boolean
  /** A local import's folders that are missing right now; the import waits for them. */
  waiting_for: string[]
  counts: ImportCounts
  group_count: number
  /** Groups with nothing left to import (once planned). */
  groups_done: number
  /** Gallery groups the review editor can open (the detail's ``reviewable_group_ids``) */
  groups_reviewable: number
  created_at: string | null
  updated_at: string | null
  completed_at: string | null
  last_upload_at: string | null
  /**
   * The latest refinement of the import's map groups (merged where their content shows one map;
   * ADR-028): a top-level folder's, as each finishes in a large import, or the whole import's.
   * Null until the first. The gallery refreshes when it changes.
   */
  grouping_refined_at: string | null
}

export interface ImportJobDetail extends ImportJobSummary {
  groups: ImportGroupSummary[]
  /**
   * Gallery groups with an image from this import and no unfinished import group of it
   * adding to them: what the review editor may open. The rule lives only on the server
   * (design/import-progress.md §5).
   */
  reviewable_group_ids: number[]
}

export interface QueueStatus {
  running: boolean
  system_paused: boolean
  reason: string | null
  current_job_id: string | null
  /** Rolling average seconds to import one file this session; null until measured. */
  seconds_per_item?: number | null
}

export interface ImportJobList {
  jobs: ImportJobSummary[]
  queue: QueueStatus
  version: number
}

export interface ManifestFile {
  client_ref?: string
  relative_path: string
  size?: number
  last_modified?: number
  image_type?: ImageType
}

export interface ManifestItemResult {
  client_ref: string | null
  item_id: number
  relative_path: string
  state: ItemState
  error_reason: string | null
}

export interface ManifestResponse {
  items: ManifestItemResult[]
  ignored: number
}

export interface HashResult {
  item_id: number
  state: ItemState
  duplicate_of_image_id: number | null
}

export interface ContentResult {
  item_id: number
  state: ItemState
  error_reason: string | null
  duplicate_of_image_id: number | null
}

/** What POST /imports/{id}/local-sources added. */
export interface LocalSourcesResult {
  created: number
  skipped: number
  failed: number
  ignored: number
}

export interface ArchiveResult {
  name: string
  created: number
  skipped: number
  failed: number
}

export interface ImportItem {
  id: number
  job_id: string
  import_group_id: number | null
  kind: 'image' | 'video' | 'archive'
  relative_path: string
  filename: string
  image_type: string
  size: number | null
  state: ItemState
  attempts: number
  /**
   * sorted_out: skipped by Auto, can be included (design/ingestion.md §5.6).
   * sorted_out_expired: one whose bytes and preview were released; now a plain skip.
   */
  error_kind:
    'file' | 'transient' | 'system' | 'bytes_lost' | 'sorted_out' | 'sorted_out_expired' | null
  error_stage: string | null
  error_reason: string | null
  image_id: number | null
  duplicate_of_image_id: number | null
  duplicate_tier: 'bytes' | 'pixels' | null
  allow_duplicate: boolean
  similar_to_image_id: number | null
  updated_at: string | null
  /** Auto items: the image-type head's verdict */
  classification: ItemClassification | null
  /** Items Auto sorted out keep a preview (importPreviewUrl) until they expire */
  has_preview: boolean
}

export interface ItemClassification {
  group: 'map' | 'illustration' | 'token' | 'asset' | 'other'
  probabilities: Record<string, number>
  fell_back: boolean
  head: string
}

/** Items Auto sorted out of one gallery group, across imports */
export interface SortedOutList {
  items: ImportItem[]
  truncated: boolean
}

export interface IncludeResult {
  affected: number
  job_ids: string[]
}

export interface ImportItemPage {
  items: ImportItem[]
  next_after: number | null
}

export interface ActionResult {
  affected: number
  status: string
}

/** A file chosen by the user, with its path relative to the picked folder or drop. */
export interface PickedFile {
  file: File
  relativePath: string
}
