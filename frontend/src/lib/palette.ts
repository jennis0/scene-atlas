/** Colour palette, independent of light/dark: each has both modes (see index.css). */
export type Palette = 'navy' | 'verdigris' | 'lapis' | 'sienna' | 'nightshade'
export const PALETTES: readonly { value: Palette; label: string; title: string }[] = [
  { value: 'navy', label: 'Navy & gold', title: 'Deep navy with gold accents' },
  { value: 'verdigris', label: 'Ink & verdigris', title: 'Green-black ink with verdigris accents' },
  { value: 'lapis', label: 'Slate & lapis', title: 'Cool grey slate with lapis blue accents' },
  {
    value: 'sienna',
    label: 'Walnut & sienna',
    title: 'Warm walnut brown with burnt sienna accents',
  },
  {
    value: 'nightshade',
    label: 'Nightshade & amethyst',
    title: 'Dusky plum with amethyst accents',
  },
]

export const PALETTE_STORAGE_KEY = 'scene-atlas-palette'

/** Read the saved palette; anything unknown falls back to the default. */
export function getStoredPalette(): Palette {
  try {
    const stored = localStorage.getItem(PALETTE_STORAGE_KEY)
    return PALETTES.find((p) => p.value === stored)?.value ?? 'navy'
  } catch {
    return 'navy'
  }
}

/** The default palette is the base tokens, so only other palettes set the attribute. */
export function applyPalette(palette: Palette) {
  if (palette === 'navy') delete document.documentElement.dataset.palette
  else document.documentElement.dataset.palette = palette
}
