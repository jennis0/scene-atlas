import type { FilterOptionGroup } from '@/components/FilterMenuContent'

export interface ActiveFilter {
  type: 'subgroup' | 'tag' | 'gridded' | 'author' | 'color' | 'media_type'
  value: string // subgroup text | "category:value" | "gridded"/"gridless"/"unknown" | author name | hex color | "image"/"video"
  label: string // display text for chip
  exclude: boolean
}

export type ImageTypeFilter = 'all' | 'battlemap' | 'scene'

export interface FileFilter {
  text: string
  imageType: ImageTypeFilter
  active: ActiveFilter[]
}

export const EMPTY_FILTER: FileFilter = { text: '', imageType: 'all', active: [] }

/** The fields client-side filtering reads; editor files and API images both have them. */
export interface FilterableItem {
  name: string
  filename: string
  subgroup: string | null
  image_type?: 'battlemap' | 'scene'
  media_type?: string
  gridded: boolean | null
  grid_type: string | null
  tags: { category: string; value: string }[]
}

const matchesNameOrFilename = (item: FilterableItem, text: string) =>
  item.filename.toLowerCase().includes(text) || item.name.toLowerCase().includes(text)

/** Whether `item` has the filtered property, ignoring `exclude`; null for types filtered server-side. */
function matchesActiveFilter(item: FilterableItem, af: ActiveFilter): boolean | null {
  switch (af.type) {
    case 'subgroup':
      return item.subgroup === af.value
    case 'tag': {
      const colonIdx = af.value.indexOf(':')
      const cat = af.value.slice(0, colonIdx)
      const val = af.value.slice(colonIdx + 1)
      return item.tags.some((t) => t.category === cat && t.value === val)
    }
    case 'gridded':
      if (af.value === 'square' || af.value === 'hex') {
        return item.gridded === true && item.grid_type === af.value
      }
      return (
        item.gridded === (af.value === 'gridded' ? true : af.value === 'gridless' ? false : null)
      )
    case 'media_type':
      return (item.media_type ?? 'image') === af.value
    default:
      return null
  }
}

/** Filters are ANDed; `matchesText` receives the lower-cased search text. */
export function applyFileFilter<T extends FilterableItem>(
  items: T[],
  filter: FileFilter,
  matchesText: (item: T, text: string) => boolean = matchesNameOrFilename,
): T[] {
  const text = filter.text.toLowerCase()
  return items.filter((item) => {
    if (text && !matchesText(item, text)) return false
    if (filter.imageType !== 'all' && (item.image_type ?? 'battlemap') !== filter.imageType) {
      return false
    }
    return filter.active.every((af) => {
      const match = matchesActiveFilter(item, af)
      return match === null || match !== af.exclude
    })
  })
}

/** One filter group per tag category, values ordered by how many items carry them. */
export function buildTagFilterGroups(items: FilterableItem[]): FilterOptionGroup[] {
  const counts = new Map<string, Map<string, number>>()
  for (const item of items) {
    for (const { category, value } of item.tags) {
      const values = counts.get(category) ?? new Map<string, number>()
      values.set(value, (values.get(value) ?? 0) + 1)
      counts.set(category, values)
    }
  }
  return [...counts].map(([category, values]) => ({
    id: category,
    label: category,
    type: 'tag',
    options: [...values]
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({
        filterValue: `${category}:${value}`,
        label: value,
        filterLabel: `${category}: ${value}`,
        count,
      })),
  }))
}
