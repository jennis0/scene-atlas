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
  // Where the grid came from: 'filename' | 'detector' | 'user' | null
  grid_source?: string | null
  subgroup: string | null
  image_type: 'battlemap' | 'scene'
  thumbnail_key: string | null
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
  icon: string | null // Lucide icon name, e.g. "leaf"
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
  scores?: Record<number, number> // image_id -> RRF relevance score
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

export interface TagPack {
  name: string
  label: string
  description: string
  tag_count: number
  imported: boolean
  new_tags: number
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

// Per-image tag as edited in the group editor
export interface TagData {
  category: string
  value: string
  confidence: number
  source: string
}

// Group editor state (frontend only)
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
  previewUrl?: string // Thumbnail URL
  fullImageUrl?: string // Full-res URL (edit mode); falls back to previewUrl in lightbox
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

// Group picker/merge types
export interface GroupPickerItem {
  id: number
  base_name: string
  author: string | null
  primary_image_id: number | null
  image_count: number
}

export interface GroupPickerResponse {
  groups: GroupPickerItem[]
  total: number
}

// Group search types (for grouped view)
export interface GroupSearchResult {
  group_id: number
  base_name: string
  author: string | null
  hero_image: Image
  mosaic_images: Image[]
  total_scenes: number
  matching_scenes: number
  best_score: number | null
  all_image_ids?: number[] // populated when include_all_image_ids=true
}

/** Minimal image reference for mass-edit seeding — only id and group_id needed. */
export type SeedImage = { id: number; group_id: number | null }

export interface GroupSearchResponse {
  total_groups: number
  limit: number
  offset: number
  groups: GroupSearchResult[]
}

export interface GroupMergeResponse {
  target_group_id: number
  target_group_name: string
  images_moved: number
  source_group_deleted: boolean
}

export interface MoveImagesResponse {
  source_group_id: number
  target_group_id: number
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
  icon: string | null
  values: string[]
  aliases: Record<string, string[]> // canonical value → alias list
}

// ── App Settings ──────────────────────────────────────────────────────────────

export interface AppSettings {
  // AI model selection: "" = auto-detect; "small" | "medium" | "large" once set
  active_model: string

  // Grid detection (image analysis)
  enable_image_grid_detection: boolean
  // Longest side analysed for grids; 0 = full resolution
  grid_analysis_max_dim: number

  // Color extraction
  num_dominant_colors: number
  color_distance_threshold: number
  color_clustering_samples: number
  color_kmeans_n_init: number

  // Ingestion performance
  ingestion_batch_size: number
  max_concurrent_prepare: number
  max_concurrent_heavy_requests: number

  // Import limits
  max_import_file_size: number
  max_video_file_size: number
  max_import_files: number
  max_import_total_size: number

  // Import options
  convert_to_webp: boolean

  // Job runner (takes effect on next restart)
  max_job_workers: number
  scheduler_enabled: boolean
}
