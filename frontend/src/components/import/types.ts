import type { TagCategory, ParsedTagVocab } from '@/types'

// Re-export so component-layer files can import from this module
export type { ParsedTagVocab }

export function parseTagVocabulary(categories: TagCategory[]): ParsedTagVocab[] {
  return categories
    .map((cat) => {
      let values: string[] = []
      if (cat.common_values) {
        try {
          const parsed = JSON.parse(cat.common_values)
          values = parsed.map((entry: string | { value: string }) =>
            typeof entry === 'string' ? entry : entry.value,
          )
        } catch {
          /* skip malformed */
        }
      }
      return { category: cat.name, values }
    })
    .filter((v) => v.values.length > 0)
}

export function humanizeFilename(filename: string): string {
  return filename
    .replace(/\.[^.]+$/, '') // strip extension
    .replace(/[_-]+/g, ' ') // underscores/dashes → spaces
    .replace(/\s+/g, ' ')
    .trim()
}
