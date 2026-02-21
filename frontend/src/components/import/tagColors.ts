export interface TagColor {
  bg: string
  text: string
  border: string
  dot: string   // solid background colour for dot indicators
}

export const CATEGORY_COLORS: Record<string, TagColor> = {
  lighting:    { bg: 'bg-amber-400/10',   text: 'text-amber-300',   border: 'border-amber-400/30',   dot: 'bg-amber-400' },
  weather:     { bg: 'bg-sky-400/10',     text: 'text-sky-300',     border: 'border-sky-400/30',     dot: 'bg-sky-400' },
  season:      { bg: 'bg-orange-400/10',  text: 'text-orange-300',  border: 'border-orange-400/30',  dot: 'bg-orange-400' },
  terrain:     { bg: 'bg-emerald-400/10', text: 'text-emerald-300', border: 'border-emerald-400/30', dot: 'bg-emerald-500' },
  biome:       { bg: 'bg-green-400/10',   text: 'text-green-300',   border: 'border-green-400/30',   dot: 'bg-green-500' },
  environment: { bg: 'bg-teal-400/10',    text: 'text-teal-300',    border: 'border-teal-400/30',    dot: 'bg-teal-500' },
  structure:   { bg: 'bg-stone-400/10',   text: 'text-stone-300',   border: 'border-stone-400/30',   dot: 'bg-stone-400' },
  feature:     { bg: 'bg-violet-400/10',  text: 'text-violet-300',  border: 'border-violet-400/30',  dot: 'bg-violet-500' },
  mood:        { bg: 'bg-rose-400/10',    text: 'text-rose-300',    border: 'border-rose-400/30',    dot: 'bg-rose-400' },
}

export const DEFAULT_TAG_COLOR: TagColor = { bg: 'bg-zinc-400/10', text: 'text-zinc-300', border: 'border-zinc-400/30', dot: 'bg-zinc-400' }

export function getTagColor(category: string): TagColor {
  return CATEGORY_COLORS[category.toLowerCase()] ?? DEFAULT_TAG_COLOR
}
