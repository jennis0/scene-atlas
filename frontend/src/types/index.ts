export interface Image {
  id: number
  storage_key: string
  filename: string
  author: string
  name: string
  variant_group_id: number | null
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
  text?: string
  semantic?: string
  authors?: string[]
  tags?: string[]
  exclude_tags?: string[]
  colors?: string[]
  gridded?: boolean
  min_width?: number
  min_height?: number
  limit?: number
  offset?: number
}

export interface SearchResult {
  total: number
  images: Image[]
  limit: number
  offset: number
}

export interface SemanticSearchResult {
  image_id: number
  score: number
  image: Image
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

// Import types — upload response (from analysis)
export interface ImportFileInfo {
  relative_path: string
  filename: string
  detected_tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
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

// Import types — confirm request (full per-file metadata)
export interface TagData {
  category: string
  value: string
  confidence: number
  source: string
}

export interface ImportConfirmFile {
  relative_path: string
  tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
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
  tags: TagData[]
  gridded: boolean | null
  grid_width: number | null
  grid_height: number | null
  sub_variant: string | null
  excluded: boolean
}

export interface EditableGroupState {
  id: string
  author: string
  variant_group_name: string
  files: EditableFileState[]
  skip: boolean
  status: 'pending' | 'running' | 'completed' | 'failed'
  processed: number
  failed: number
  total: number
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
