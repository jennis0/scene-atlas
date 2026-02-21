export interface TagColor {
  bg: string
  text: string
  border: string
}

export const CATEGORY_COLORS: Record<string, TagColor> = {
  lighting:    { bg: 'bg-amber-50',    text: 'text-amber-700',    border: 'border-amber-200' },
  weather:     { bg: 'bg-sky-50',      text: 'text-sky-700',      border: 'border-sky-200' },
  season:      { bg: 'bg-orange-50',   text: 'text-orange-700',   border: 'border-orange-200' },
  terrain:     { bg: 'bg-emerald-50',  text: 'text-emerald-700',  border: 'border-emerald-200' },
  biome:       { bg: 'bg-green-50',    text: 'text-green-700',    border: 'border-green-200' },
  environment: { bg: 'bg-teal-50',     text: 'text-teal-700',     border: 'border-teal-200' },
  structure:   { bg: 'bg-stone-50',    text: 'text-stone-700',    border: 'border-stone-200' },
  feature:     { bg: 'bg-violet-50',   text: 'text-violet-700',   border: 'border-violet-200' },
  mood:        { bg: 'bg-rose-50',     text: 'text-rose-700',     border: 'border-rose-200' },
}

export const DEFAULT_TAG_COLOR: TagColor = { bg: 'bg-slate-50', text: 'text-slate-700', border: 'border-slate-200' }

export function getTagColor(category: string): TagColor {
  return CATEGORY_COLORS[category.toLowerCase()] ?? DEFAULT_TAG_COLOR
}
