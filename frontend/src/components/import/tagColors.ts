export interface TagColor {
  bg: string
  text: string
  border: string
  dot: string   // solid background colour for dot indicators
}

/**
 * Full palette of Tailwind color presets.
 * Keyed by Tailwind color name — this is what gets stored in the DB.
 */
export const COLOR_PALETTE: Record<string, TagColor> = {
  red:      { bg: 'bg-red-400/10',     text: 'text-red-300',     border: 'border-red-400/30',     dot: 'bg-red-400' },
  crimson:  { bg: 'bg-red-900/20',     text: 'text-red-200',     border: 'border-red-900/30',     dot: 'bg-red-800' },
  orange:   { bg: 'bg-orange-400/10',  text: 'text-orange-300',  border: 'border-orange-400/30',  dot: 'bg-orange-400' },
  amber:    { bg: 'bg-amber-400/10',   text: 'text-amber-300',   border: 'border-amber-400/30',   dot: 'bg-amber-400' },
  brown:    { bg: 'bg-amber-800/20',   text: 'text-amber-200',   border: 'border-amber-800/30',   dot: 'bg-amber-800' },
  yellow:   { bg: 'bg-yellow-400/10',  text: 'text-yellow-300',  border: 'border-yellow-400/30',  dot: 'bg-yellow-400' },
  lime:     { bg: 'bg-lime-400/10',    text: 'text-lime-300',    border: 'border-lime-400/30',    dot: 'bg-lime-400' },
  green:    { bg: 'bg-green-400/10',   text: 'text-green-300',   border: 'border-green-400/30',   dot: 'bg-green-500' },
  emerald:  { bg: 'bg-emerald-400/10', text: 'text-emerald-300', border: 'border-emerald-400/30', dot: 'bg-emerald-500' },
  teal:     { bg: 'bg-teal-400/10',    text: 'text-teal-300',    border: 'border-teal-400/30',    dot: 'bg-teal-500' },
  cyan:     { bg: 'bg-cyan-400/10',    text: 'text-cyan-300',    border: 'border-cyan-400/30',    dot: 'bg-cyan-400' },
  sky:      { bg: 'bg-sky-400/10',     text: 'text-sky-300',     border: 'border-sky-400/30',     dot: 'bg-sky-400' },
  blue:     { bg: 'bg-blue-400/10',    text: 'text-blue-300',    border: 'border-blue-400/30',    dot: 'bg-blue-400' },
  indigo:   { bg: 'bg-indigo-400/10',  text: 'text-indigo-300',  border: 'border-indigo-400/30',  dot: 'bg-indigo-400' },
  violet:   { bg: 'bg-violet-400/10',  text: 'text-violet-300',  border: 'border-violet-400/30',  dot: 'bg-violet-500' },
  purple:   { bg: 'bg-purple-400/10',  text: 'text-purple-300',  border: 'border-purple-400/30',  dot: 'bg-purple-400' },
  fuchsia:  { bg: 'bg-fuchsia-400/10', text: 'text-fuchsia-300', border: 'border-fuchsia-400/30', dot: 'bg-fuchsia-400' },
  pink:     { bg: 'bg-pink-400/10',    text: 'text-pink-300',    border: 'border-pink-400/30',    dot: 'bg-pink-400' },
  rose:     { bg: 'bg-rose-400/10',    text: 'text-rose-300',    border: 'border-rose-400/30',    dot: 'bg-rose-400' },
  stone:    { bg: 'bg-stone-400/10',   text: 'text-stone-300',   border: 'border-stone-400/30',   dot: 'bg-stone-400' },
  slate:    { bg: 'bg-slate-400/10',   text: 'text-slate-300',   border: 'border-slate-400/30',   dot: 'bg-slate-400' },
  gray:     { bg: 'bg-gray-400/10',    text: 'text-gray-300',    border: 'border-gray-400/30',    dot: 'bg-gray-400' },
  zinc:     { bg: 'bg-zinc-400/10',    text: 'text-zinc-300',    border: 'border-zinc-400/30',    dot: 'bg-zinc-400' },
  neutral:  { bg: 'bg-neutral-400/10', text: 'text-neutral-300', border: 'border-neutral-400/30', dot: 'bg-neutral-400' },
}

/** Ordered list of palette keys for rendering color pickers */
export const PALETTE_KEYS = Object.keys(COLOR_PALETTE)

export const DEFAULT_TAG_COLOR: TagColor = {
  bg: 'bg-zinc-400/10',
  text: 'text-zinc-300',
  border: 'border-zinc-400/30',
  dot: 'bg-zinc-400',
}

/**
 * Look up a TagColor by Tailwind color name.
 * Pass the color name from the DB (e.g. "amber", "sky").
 */
export function getTagColor(colorName: string | null | undefined): TagColor {
  if (!colorName) return DEFAULT_TAG_COLOR
  return COLOR_PALETTE[colorName.toLowerCase()] ?? DEFAULT_TAG_COLOR
}
