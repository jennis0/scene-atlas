import { displayChoice } from './displayChoice'

/** Colour palette, independent of light/dark: each has both modes (see index.css).
 * The values are the original names, kept so saved choices still apply; labels are what users see. */
export type Palette = 'navy' | 'verdigris' | 'lapis' | 'sienna' | 'nightshade'
export const PALETTES: readonly { value: Palette; label: string; title: string }[] = [
  { value: 'navy', label: 'Navy', title: 'Deep navy with gold accents' },
  { value: 'verdigris', label: 'Green', title: 'Dark green with copper-green accents' },
  { value: 'lapis', label: 'Slate', title: 'Cool grey with blue accents' },
  { value: 'sienna', label: 'Brown', title: 'Warm brown with orange accents' },
  { value: 'nightshade', label: 'Plum', title: 'Plum with violet accents' },
]

export const PALETTE_STORAGE_KEY = 'scene-atlas-palette'

export const paletteChoice = displayChoice<Palette>(
  PALETTE_STORAGE_KEY,
  'palette',
  PALETTES.map((p) => p.value),
  'navy',
)

/** The saved palette; anything unknown falls back to navy, the default. */
export const getStoredPalette = paletteChoice.read
/** Navy is the base tokens, so only other palettes set data-palette. */
export const applyPalette = paletteChoice.apply
