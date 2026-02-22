export interface Image {
  id: number
  storage_key: string
  filename: string
  author: string
  name: string
  variant_group_id: number | null
  variant_group_name: string | null
  variant_group_image_count: number | null
  created_at: string
  updated_at: string
  file_size: number
  width: number
  height: number
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
  thumbnail_key: string | null
  needs_review: boolean
  tags: Tag[]
  colors: Color[]
}

export interface VariantGroup {
  id: number
  base_name: string
  author: string
  description: string | null
  created_at: string
  updated_at: string
  image_count: number
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
  color: string | null  // Tailwind color preset name
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

export interface SearchParams {
  query?: string            // hybrid: FTS5 + semantic
  semantic_only?: boolean   // skip FTS5, pure semantic (from ~ prefix)
  text_only?: boolean       // skip CLIP, FTS keyword only (from = prefix)
  authors?: string[]
  exclude_authors?: string[]
  tags?: string[]
  exclude_tags?: string[]
  colors?: string[]
  gridded?: boolean
  limit?: number
  offset?: number
}

export interface FacetOption {
  value: string
  count: number
}

export interface FacetData {
  total_images: number
  authors: FacetOption[]
  tags: Record<string, FacetOption[]>  // category → values sorted by count
  gridded: { gridded: number; gridless: number; unknown: number }
  colors: { hex: string; count: number }[]
}

export interface SearchResult {
  total: number
  images: Image[]
  limit: number
  offset: number
  scores?: Record<number, number>  // image_id -> semantic score
}

export type ViewMode = 'individual' | 'grouped'

export interface ImageGroup {
  groupId: number | null
  baseName: string
  author: string
  heroImage: Image
  mosaicImages: Image[]
  totalVariants: number
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
  categories: Record<string, {
    total_tags: number
    unique_values: number
  }>
}

// Import types — duplicate detection
export interface DuplicateInfo {
  image_id: number
  name: string | null
  author: string | null
  storage_key: string
  thumbnail_key: string | null
  variant_group_name: string | null
}

// Import types — upload response (from analysis)
export interface ImportFileInfo {
  relative_path: string
  filename: string
  detected_tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
  content_hash: string | null
  duplicate_of: DuplicateInfo | null
}

export interface ImportVariantGroup {
  author: string | null
  variant_group_name: string
  files: ImportFileInfo[]
}

export interface ImportUploadResponse {
  job_id: string
  total_files: number
  variant_groups: ImportVariantGroup[]
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
  tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
  content_hash?: string
  reuse_storage_key?: string
  reuse_thumbnail_key?: string
}

export interface ImportConfirmRequest {
  author: string
  variant_group_name: string
  files: ImportConfirmFile[]
}

// Import types — editable state (frontend only)
export interface EditableFileState {
  relative_path: string
  filename: string
  name: string
  tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
  excluded: boolean
  outOfScope?: boolean  // true = in group but not in search results (mass-edit context only)
  previewUrl?: string  // Browser blob URL (for direct uploads) or server preview URL (for ZIP)
  fullImageUrl?: string  // Full-res URL (edit mode); falls back to previewUrl in lightbox
  content_hash?: string  // SHA-256 content hash
  duplicate_of?: DuplicateInfo | null  // Existing image this file matches
  duplicate_action?: 'skip' | 'import'  // User's choice for duplicate files
}

export interface EditableGroupState {
  id: string
  author: string
  variant_group_name: string
  files: EditableFileState[]
  skip: boolean
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  processed: number
  failed: number
  total: number
}

// Variant group search/merge types
export interface VariantGroupSearchItem {
  id: number
  base_name: string
  author: string | null
  primary_image_id: number | null
  image_count: number
}

export interface VariantGroupSearchResponse {
  groups: VariantGroupSearchItem[]
  total: number
}

export interface VariantGroupMergeResponse {
  target_group_id: number
  target_group_name: string
  images_moved: number
  source_group_deleted: boolean
}

// Variant group edit types
export interface VariantGroupDetail {
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
  sub_variant?: string | null
}

export interface NewGroupPayload {
  base_name: string
  author?: string
  image_ids: number[]
}

export interface VariantGroupEditRequest {
  base_name: string
  author?: string
  images: ImageEditPayload[]
  new_groups: NewGroupPayload[]
}

// Import types — status response
export interface ImportGroupStatus {
  variant_group_name: string
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
