import type { TagCategory, ParsedTagVocab } from '@/types'

// Re-export so component-layer files can import from this module
export type { ParsedTagVocab }

export interface TagValueEntry {
  value: string
  aliases: string[]
}

/** Parses a category's `common_values` JSON (plain strings or `{ value, aliases }`). */
export function parseCommonValues(raw: string | null): TagValueEntry[] {
  if (!raw) return []
  try {
    const arr = JSON.parse(raw) as (string | { value: string; aliases?: string[] })[]
    return arr.map((v) =>
      typeof v === 'string'
        ? { value: v, aliases: [] }
        : { value: v.value, aliases: v.aliases ?? [] },
    )
  } catch (e) {
    console.warn('Failed to parse common_values JSON:', e)
    return []
  }
}

export function parseTagVocabulary(categories: TagCategory[]): ParsedTagVocab[] {
  return categories
    .map((cat) => {
      const entries = parseCommonValues(cat.common_values)
      const aliases: Record<string, string[]> = {}
      for (const { value, aliases: a } of entries) {
        if (a.length > 0) aliases[value] = a
      }
      return { category: cat.name, icon: cat.icon, values: entries.map((e) => e.value), aliases }
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
