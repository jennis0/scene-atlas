import { displayChoice } from './displayChoice'

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

const choice = displayChoice<Palette>(
  PALETTE_STORAGE_KEY,
  'palette',
  PALETTES.map((p) => p.value),
  'navy',
)

/** The saved palette; anything unknown falls back to navy, the default. */
export const getStoredPalette = choice.read
/** Navy is the base tokens, so only other palettes set data-palette. */
export const applyPalette = choice.apply
export const savePalette = choice.save
