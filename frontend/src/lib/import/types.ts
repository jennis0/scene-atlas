/**
 * Types for the imports API (ADR-018, design/ingestion.md §7).
 * Mirrors backend/app/models/import_schemas.py.
 */

export type ImageType = 'battlemap' | 'scene'

export type ItemState =
  | 'awaiting_bytes'
  | 'ready'
  | 'processing'
  | 'done'
  | 'duplicate'
  | 'failed'
  | 'skipped'

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
}

export interface ImportGroupSummary {
  id: number
  author: string | null
  group_name: string
  image_group_id: number | null
  merged_into_existing: boolean
  sort_order: number
  counts: ImportCounts
}

export interface ImportJobSummary {
  id: string
  label: string | null
  status: JobStatus
  default_image_type: ImageType
  planned: boolean
  dismissed: boolean
  upload_interrupted: boolean
  counts: ImportCounts
  group_count: number
  created_at: string | null
  updated_at: string | null
  completed_at: string | null
  last_upload_at: string | null
}

export interface ImportJobDetail extends ImportJobSummary {
  groups: ImportGroupSummary[]
}

export interface QueueStatus {
  running: boolean
  system_paused: boolean
  reason: string | null
  current_job_id: string | null
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

export interface ArchiveResult {
  name: string
  created: number
  skipped: number
  failed: number
}

export interface ImportItem {
  id: number
  import_group_id: number | null
  kind: 'image' | 'video' | 'archive'
  relative_path: string
  filename: string
  image_type: string
  size: number | null
  state: ItemState
  attempts: number
  error_kind: 'file' | 'transient' | 'system' | 'bytes_lost' | null
  error_stage: string | null
  error_reason: string | null
  image_id: number | null
  duplicate_of_image_id: number | null
  duplicate_tier: 'bytes' | 'pixels' | null
  allow_duplicate: boolean
  similar_to_image_id: number | null
  updated_at: string | null
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
