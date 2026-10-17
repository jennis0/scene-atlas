import type { Theme } from '@/contexts/ThemeContext'

export interface TagColor {
  bg: string
  text: string
  border: string
  dot: string // solid background colour for dot indicators
}

/** Internal palette entry — stores both dark and light variants */
interface TagColorEntry {
  bg: string
  text: string
  border: string
  dot: string
  lightBg: string
  lightText: string
  lightBorder: string
}

/**
 * Full palette of Tailwind color presets.
 * Keyed by Tailwind color name — this is what gets stored in the DB.
 * Each entry has dark-mode classes (bg/text/border/dot) and light-mode
 * counterparts (lightBg/lightText/lightBorder). Same hue, different shades.
 */
const COLOR_PALETTE: Record<string, TagColorEntry> = {
  red: {
    bg: 'bg-red-400/10',
    text: 'text-red-300',
    border: 'border-red-400/30',
    dot: 'bg-red-400',
    lightBg: 'bg-red-50',
    lightText: 'text-red-800',
    lightBorder: 'border-red-200',
  },
  crimson: {
    bg: 'bg-red-900/20',
    text: 'text-red-200',
    border: 'border-red-900/30',
    dot: 'bg-red-800',
    lightBg: 'bg-red-100',
    lightText: 'text-red-900',
    lightBorder: 'border-red-300',
  },
  orange: {
    bg: 'bg-orange-400/10',
    text: 'text-orange-300',
    border: 'border-orange-400/30',
    dot: 'bg-orange-400',
    lightBg: 'bg-orange-50',
    lightText: 'text-orange-800',
    lightBorder: 'border-orange-200',
  },
  amber: {
    bg: 'bg-amber-400/10',
    text: 'text-amber-300',
    border: 'border-amber-400/30',
    dot: 'bg-amber-400',
    lightBg: 'bg-amber-50',
    lightText: 'text-amber-800',
    lightBorder: 'border-amber-200',
  },
  brown: {
    bg: 'bg-amber-800/20',
    text: 'text-amber-200',
    border: 'border-amber-800/30',
    dot: 'bg-amber-800',
    lightBg: 'bg-amber-100',
    lightText: 'text-amber-900',
    lightBorder: 'border-amber-300',
  },
  yellow: {
    bg: 'bg-yellow-400/10',
    text: 'text-yellow-300',
    border: 'border-yellow-400/30',
    dot: 'bg-yellow-400',
    lightBg: 'bg-yellow-50',
    lightText: 'text-yellow-800',
    lightBorder: 'border-yellow-200',
  },
  lime: {
    bg: 'bg-lime-400/10',
    text: 'text-lime-300',
    border: 'border-lime-400/30',
    dot: 'bg-lime-400',
    lightBg: 'bg-lime-50',
    lightText: 'text-lime-800',
    lightBorder: 'border-lime-200',
  },
  green: {
    bg: 'bg-green-400/10',
    text: 'text-green-300',
    border: 'border-green-400/30',
    dot: 'bg-green-500',
    lightBg: 'bg-green-50',
    lightText: 'text-green-800',
    lightBorder: 'border-green-200',
  },
  emerald: {
    bg: 'bg-emerald-400/10',
    text: 'text-emerald-300',
    border: 'border-emerald-400/30',
    dot: 'bg-emerald-500',
    lightBg: 'bg-emerald-50',
    lightText: 'text-emerald-800',
    lightBorder: 'border-emerald-200',
  },
  teal: {
    bg: 'bg-teal-400/10',
    text: 'text-teal-300',
    border: 'border-teal-400/30',
    dot: 'bg-teal-500',
    lightBg: 'bg-teal-50',
    lightText: 'text-teal-800',
    lightBorder: 'border-teal-200',
  },
  cyan: {
    bg: 'bg-cyan-400/10',
    text: 'text-cyan-300',
    border: 'border-cyan-400/30',
    dot: 'bg-cyan-400',
    lightBg: 'bg-cyan-50',
    lightText: 'text-cyan-800',
    lightBorder: 'border-cyan-200',
  },
  sky: {
    bg: 'bg-sky-400/10',
    text: 'text-sky-300',
    border: 'border-sky-400/30',
    dot: 'bg-sky-400',
    lightBg: 'bg-sky-50',
    lightText: 'text-sky-800',
    lightBorder: 'border-sky-200',
  },
  blue: {
    bg: 'bg-blue-400/10',
    text: 'text-blue-300',
    border: 'border-blue-400/30',
    dot: 'bg-blue-400',
    lightBg: 'bg-blue-50',
    lightText: 'text-blue-800',
    lightBorder: 'border-blue-200',
  },
  indigo: {
    bg: 'bg-indigo-400/10',
    text: 'text-indigo-300',
    border: 'border-indigo-400/30',
    dot: 'bg-indigo-400',
    lightBg: 'bg-indigo-50',
    lightText: 'text-indigo-800',
    lightBorder: 'border-indigo-200',
  },
  violet: {
    bg: 'bg-violet-400/10',
    text: 'text-violet-300',
    border: 'border-violet-400/30',
    dot: 'bg-violet-500',
    lightBg: 'bg-violet-50',
    lightText: 'text-violet-800',
    lightBorder: 'border-violet-200',
  },
  purple: {
    bg: 'bg-purple-400/10',
    text: 'text-purple-300',
    border: 'border-purple-400/30',
    dot: 'bg-purple-400',
    lightBg: 'bg-purple-50',
    lightText: 'text-purple-800',
    lightBorder: 'border-purple-200',
  },
  fuchsia: {
    bg: 'bg-fuchsia-400/10',
    text: 'text-fuchsia-300',
    border: 'border-fuchsia-400/30',
    dot: 'bg-fuchsia-400',
    lightBg: 'bg-fuchsia-50',
    lightText: 'text-fuchsia-800',
    lightBorder: 'border-fuchsia-200',
  },
  pink: {
    bg: 'bg-pink-400/10',
    text: 'text-pink-300',
    border: 'border-pink-400/30',
    dot: 'bg-pink-400',
    lightBg: 'bg-pink-50',
    lightText: 'text-pink-800',
    lightBorder: 'border-pink-200',
  },
  rose: {
    bg: 'bg-rose-400/10',
    text: 'text-rose-300',
    border: 'border-rose-400/30',
    dot: 'bg-rose-400',
    lightBg: 'bg-rose-50',
    lightText: 'text-rose-800',
    lightBorder: 'border-rose-200',
  },
  stone: {
    bg: 'bg-stone-400/10',
    text: 'text-stone-300',
    border: 'border-stone-400/30',
    dot: 'bg-stone-400',
    lightBg: 'bg-stone-100',
    lightText: 'text-stone-700',
    lightBorder: 'border-stone-300',
  },
  slate: {
    bg: 'bg-slate-400/10',
    text: 'text-slate-300',
    border: 'border-slate-400/30',
    dot: 'bg-slate-400',
    lightBg: 'bg-slate-100',
    lightText: 'text-slate-700',
    lightBorder: 'border-slate-300',
  },
  gray: {
    bg: 'bg-gray-400/10',
    text: 'text-gray-300',
    border: 'border-gray-400/30',
    dot: 'bg-gray-400',
    lightBg: 'bg-gray-100',
    lightText: 'text-gray-700',
    lightBorder: 'border-gray-300',
  },
  zinc: {
    bg: 'bg-zinc-400/10',
    text: 'text-zinc-300',
    border: 'border-zinc-400/30',
    dot: 'bg-zinc-400',
    lightBg: 'bg-zinc-100',
    lightText: 'text-zinc-700',
    lightBorder: 'border-zinc-300',
  },
  neutral: {
    bg: 'bg-neutral-400/10',
    text: 'text-neutral-300',
    border: 'border-neutral-400/30',
    dot: 'bg-neutral-400',
    lightBg: 'bg-neutral-100',
    lightText: 'text-neutral-700',
    lightBorder: 'border-neutral-300',
  },
}

/** Ordered list of palette keys for rendering color pickers */
export const PALETTE_KEYS = Object.keys(COLOR_PALETTE)

export const DEFAULT_TAG_COLOR: TagColor = {
  bg: 'bg-zinc-400/10',
  text: 'text-zinc-300',
  border: 'border-zinc-400/30',
  dot: 'bg-zinc-400',
}

const DEFAULT_TAG_COLOR_LIGHT: TagColor = {
  bg: 'bg-zinc-100',
  text: 'text-zinc-600',
  border: 'border-zinc-300',
  dot: 'bg-zinc-400',
}

/**
 * Look up a TagColor by Tailwind color name.
 * Pass the color name from the DB (e.g. "amber", "sky"), the current theme and whether
 * high contrast is on. Returns 4-field TagColor with the matching variant classes.
 */
export function getTagColor(
  colorName: string | null | undefined,
  theme: Theme = 'dark',
  highContrast = false,
): TagColor {
  const color = lookup(colorName, theme)
  return highContrast ? toHighContrast(color, theme) : color
}

function lookup(colorName: string | null | undefined, theme: Theme): TagColor {
  const fallback = theme === 'light' ? DEFAULT_TAG_COLOR_LIGHT : DEFAULT_TAG_COLOR
  if (!colorName) return fallback
  const entry = COLOR_PALETTE[colorName.toLowerCase()]
  if (!entry) return fallback
  if (theme === 'light') {
    return { bg: entry.lightBg, text: entry.lightText, border: entry.lightBorder, dot: entry.dot }
  }
  return { bg: entry.bg, text: entry.text, border: entry.border, dot: entry.dot }
}

/** Every Tailwind colour the tag palette uses; tailwind.config.js safelists the
 * high-contrast classes below for each, since they are built at runtime. */
export const TAG_HUES = [
  ...new Set(Object.values(COLOR_PALETTE).map((e) => e.dot.split('-')[1])),
] as const

/** Text shade per hue at high contrast: the least extreme shade that still reaches 7:1
 * on its chip and bare, on every palette's surfaces (tagContrast.test.ts checks it), so
 * tags keep as much of their colour as AAA allows. */
const HIGH_CONTRAST_SHADE: Record<string, { dark: number; light: number }> = {
  amber: { dark: 300, light: 950 },
  blue: { dark: 200, light: 900 },
  cyan: { dark: 300, light: 950 },
  emerald: { dark: 300, light: 950 },
  fuchsia: { dark: 300, light: 950 },
  gray: { dark: 300, light: 700 },
  green: { dark: 300, light: 950 },
  indigo: { dark: 200, light: 900 },
  lime: { dark: 300, light: 950 },
  neutral: { dark: 300, light: 700 },
  orange: { dark: 300, light: 950 },
  pink: { dark: 200, light: 950 },
  purple: { dark: 300, light: 900 },
  red: { dark: 200, light: 950 },
  rose: { dark: 200, light: 950 },
  sky: { dark: 300, light: 950 },
  slate: { dark: 300, light: 700 },
  stone: { dark: 300, light: 700 },
  teal: { dark: 300, light: 950 },
  violet: { dark: 200, light: 900 },
  yellow: { dark: 300, light: 950 },
  zinc: { dark: 300, light: 700 },
}

/** High contrast keeps the chip's tint, deepens (or lightens) the text to the shade above
 * and gives it a solid mid-tone outline. */
function toHighContrast(color: TagColor, theme: Theme): TagColor {
  const hue = color.dot.split('-')[1]
  return {
    ...color,
    text: `text-${hue}-${HIGH_CONTRAST_SHADE[hue][theme]}`,
    border: `border-${hue}-500`,
  }
}

/**
 * Get the dot color for a palette key directly (for color picker swatches).
 * Theme-independent since dots are solid colour.
 */
export function getDotColor(colorName: string): string {
  return COLOR_PALETTE[colorName.toLowerCase()]?.dot ?? 'bg-zinc-400'
}
