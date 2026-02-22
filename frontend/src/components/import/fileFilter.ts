import type { EditableFileState } from '@/types'

export interface ActiveFilter {
  type: 'subgroup' | 'tag' | 'gridded' | 'author' | 'color'
  value: string   // subgroup text | "category:value" | "gridded"/"gridless"/"unknown" | author name | hex color
  label: string   // display text for chip
  exclude: boolean
}

export type ImageTypeFilter = 'all' | 'battlemap' | 'scene'

export interface FileFilter {
  text: string
  imageType: ImageTypeFilter
  active: ActiveFilter[]
}

export const EMPTY_FILTER: FileFilter = { text: '', imageType: 'all', active: [] }

export function applyFileFilter(files: EditableFileState[], filter: FileFilter): EditableFileState[] {
  return files.filter((f) => {
    if (filter.text) {
      const t = filter.text.toLowerCase()
      if (!f.filename.toLowerCase().includes(t) && !f.name.toLowerCase().includes(t)) return false
    }
    if (filter.imageType !== 'all') {
      if ((f.image_type ?? 'battlemap') !== filter.imageType) return false
    }
    for (const af of filter.active) {
      if (af.type === 'subgroup') {
        const match = f.subgroup === af.value
        if (af.exclude ? match : !match) return false
      } else if (af.type === 'tag') {
        const colonIdx = af.value.indexOf(':')
        const cat = af.value.slice(0, colonIdx)
        const val = af.value.slice(colonIdx + 1)
        const match = f.tags.some((t) => t.category === cat && t.value === val)
        if (af.exclude ? match : !match) return false
      } else if (af.type === 'gridded') {
        const gv = af.value === 'gridded' ? true : af.value === 'gridless' ? false : null
        const match = f.gridded === gv
        if (af.exclude ? match : !match) return false
      }
    }
    return true
  })
}
