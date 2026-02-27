import type { TagCategory, ParsedTagVocab } from '@/types'

// Re-export so component-layer files can import from this module
export type { ParsedTagVocab }

export function parseTagVocabulary(categories: TagCategory[]): ParsedTagVocab[] {
  return categories
    .map((cat) => {
      const values: string[] = []
      const aliases: Record<string, string[]> = {}
      if (cat.common_values) {
        try {
          const parsed = JSON.parse(cat.common_values) as (
            | string
            | { value: string; aliases?: string[] }
          )[]
          for (const entry of parsed) {
            if (typeof entry === 'string') {
              values.push(entry)
            } else {
              values.push(entry.value)
              if (entry.aliases && entry.aliases.length > 0) {
                aliases[entry.value] = entry.aliases
              }
            }
          }
        } catch {
          /* skip malformed */
        }
      }
      return { category: cat.name, icon: cat.icon, values, aliases }
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
