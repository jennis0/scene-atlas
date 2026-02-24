export interface Image {
  id: number
  storage_key: string
  filename: string
  author: string
  name: string
  group_id: number | null
  group_name: string | null
  group_image_count: number | null
  created_at: string
  updated_at: string
  file_size: number
  width: number
  height: number
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  grid_type: string | null
  grid_confidence: number | null
  subgroup: string | null
  image_type: 'battlemap' | 'scene'
  thumbnail_key: string | null
  needs_review: boolean
  media_type: 'image' | 'video'
  tags: Tag[]
  colors: Color[]
}

export interface Tag {
  id: number
  image_id: number
  category: string
  value: string
  confidence: number
  source: string
}

export interface TagCategory {
  id: number
  name: string
  description: string | null
  color: string | null // Tailwind color preset name
  display_order: number
  common_values: string | null // JSON string of tag values
}

export interface Color {
  id: number
  image_id: number
  color_hex: string
  percentage: number
  color_order: number
}

export type SortBy = 'created_at' | 'name' | 'relevance'
export type SortDir = 'asc' | 'desc'

export interface SearchParams {
  query?: string // hybrid: FTS5 + semantic
  semantic_only?: boolean // skip FTS5, pure semantic (from ~ prefix)
  text_only?: boolean // skip CLIP, FTS keyword only (from = prefix)
  authors?: string[]
  exclude_authors?: string[]
  tags?: string[]
  exclude_tags?: string[]
  colors?: string[]
  gridded?: boolean
  gridded_unknown?: boolean
  grid_type?: string
  image_types?: string[]
  media_types?: string[]
  limit?: number
  offset?: number
  sort_by?: SortBy
  sort_dir?: SortDir
}

export interface FacetOption {
  value: string
  count: number
}

export interface FacetData {
  total_images: number
  authors: FacetOption[]
  tags: Record<string, FacetOption[]> // category → values sorted by count
  gridded: { gridded: number; gridless: number; unknown: number; square: number; hex: number }
  colors: { hex: string; count: number }[]
  image_types: FacetOption[]
  media_types: FacetOption[]
}

export interface SearchResult {
  total: number
  images: Image[]
  limit: number
  offset: number
  scores?: Record<number, number> // image_id -> semantic score
}

export type ViewMode = 'individual' | 'grouped'

export interface ImageGroup {
  groupId: number | null
  baseName: string
  author: string
  heroImage: Image
  mosaicImages: Image[]
  totalScenes: number
  matchingCount: number
  bestScore: number | null
  aggregatedTags: Tag[]
}

export interface TagValue {
  category: string
  value: string
  count: number
}

export interface TagStats {
  total_tags: number
  categories: Record<
    string,
    {
      total_tags: number
      unique_values: number
    }
  >
}

// Import types — duplicate detection
export interface DuplicateInfo {
  image_id: number
  name: string | null
  author: string | null
  storage_key: string
  thumbnail_key: string | null
  group_name: string | null
}

// Import types — upload response (from analysis)
export interface ImportFileInfo {
  relative_path: string
  filename: string
  name: string | null
  media_type: string | null
  detected_tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  grid_type: string | null
  grid_confidence: number | null
  subgroup: string | null
  image_type: string | null
  content_hash: string | null
  duplicate_of: DuplicateInfo | null
}

export interface ImportGroup {
  author: string | null
  group_name: string
  files: ImportFileInfo[]
}

export interface ImportUploadResponse {
  job_id: string
  total_files: number
  groups: ImportGroup[]
}

// Pre-flight hash check types
export interface HashCheckItem {
  relative_path: string
  filename: string
  content_hash: string
}

export interface HashCheckResultItem {
  relative_path: string
  content_hash: string
  duplicate_of: DuplicateInfo | null
}

export interface HashCheckResponse {
  results: HashCheckResultItem[]
  total_checked: number
  duplicates_found: number
}

// Import types — confirm request (full per-file metadata)
export interface TagData {
  category: string
  value: string
  confidence: number
  source: string
}

export interface ImportConfirmFile {
  relative_path: string
  name?: string
  media_type?: string
  image_type?: string
  tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  grid_type: string | null
  subgroup: string | null
  content_hash?: string
  reuse_storage_key?: string
  reuse_thumbnail_key?: string
}

export interface ImportConfirmRequest {
  author: string
  group_name: string
  files: ImportConfirmFile[]
}

// Import types — editable state (frontend only)
export interface EditableFileState {
  relative_path: string
  filename: string
  name: string
  media_type?: string
  tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  grid_type: string | null
  subgroup: string | null
  image_type?: 'battlemap' | 'scene'
  excluded: boolean
  outOfScope?: boolean // true = in group but not in search results (mass-edit context only)
  previewUrl?: string // Browser blob URL (for direct uploads) or server preview URL (for ZIP)
  fullImageUrl?: string // Full-res URL (edit mode); falls back to previewUrl in lightbox
  content_hash?: string // SHA-256 content hash
  duplicate_of?: DuplicateInfo | null // Existing image this file matches
  duplicate_action?: 'skip' | 'import' // User's choice for duplicate files
}

export interface EditableGroupState {
  id: string
  author: string
  group_name: string
  files: EditableFileState[]
  skip: boolean
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  processed: number
  failed: number
  total: number
  /** Error message from a failed confirm, displayed in the footer */
  error?: string
}

// Group search/merge types
export interface GroupSearchItem {
  id: number
  base_name: string
  author: string | null
  primary_image_id: number | null
  image_count: number
}

export interface GroupSearchResponse {
  groups: GroupSearchItem[]
  total: number
}

export interface GroupMergeResponse {
  target_group_id: number
  target_group_name: string
  images_moved: number
  source_group_deleted: boolean
}

// Group edit types
export interface GroupDetail {
  id: number
  base_name: string
  author: string | null
  primary_image_id: number | null
  images: Image[]
}

export interface ImageEditPayload {
  id: number
  name?: string
  tags: TagData[]
  gridded?: boolean | null
  grid_width?: number | null
  grid_height?: number | null
  grid_type?: string | null
  subgroup?: string | null
  image_type?: string | null
}

export interface NewGroupPayload {
  base_name: string
  author?: string
  image_ids: number[]
}

export interface GroupEditRequest {
  base_name: string
  author?: string
  images: ImageEditPayload[]
  new_groups: NewGroupPayload[]
}

export interface GroupEditResponse {
  id: number
  new_group_ids: number[]
  deleted_image_ids: number[]
}

// Import types — status response
export interface ImportGroupStatus {
  group_name: string
  total_files: number
  processed_files: number
  failed_files: number
  status: string
}

export interface ImportJobResponse {
  job_id: string
  status: string
  groups: ImportGroupStatus[]
  created_at: string
  completed_at: string | null
}

// Import tray types
export interface ImportJobSummary {
  job_id: string
  source_label: string | null
  status: string
  total_groups: number
  completed_groups: number
  failed_groups: number
  running_groups: number
  total_files: number
  created_at: string
}

export interface ActiveImportsResponse {
  jobs: ImportJobSummary[]
}

// Background job status (from /api/v1/jobs)
export interface BackgroundJob {
  id: string
  name: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  submitted_at: string
  started_at: string | null
  finished_at: string | null
  progress: string | null
  progress_pct: number | null
  result: Record<string, unknown> | null
  error: string | null
}

// ── Tag vocabulary (parsed from TagCategory.common_values) ───────────────────

export interface ParsedTagVocab {
  category: string
  values: string[]
  aliases: Record<string, string[]> // canonical value → alias list
}

// ── App Settings ──────────────────────────────────────────────────────────────

export interface AppSettings {
  // Grid detection (image analysis)
  enable_image_grid_detection: boolean
  grid_min_cell_px: number
  grid_max_cell_px: number
  grid_detection_max_dim: number
  grid_presence_threshold: number
  grid_size_threshold: number
  grid_period_ratio_threshold: number
  grid_hex_rot_conf: number

  // Color extraction
  num_dominant_colors: number
  color_distance_threshold: number
  color_clustering_samples: number
  color_kmeans_n_init: number

  // Ingestion performance
  ingestion_batch_size: number
  max_concurrent_prepare: number

  // Import limits
  max_import_file_size: number
  max_video_file_size: number
  max_import_files: number
  max_import_total_size: number

  // Job runner (takes effect on next restart)
  max_job_workers: number
  scheduler_enabled: boolean
}
