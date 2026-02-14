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
