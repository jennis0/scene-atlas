import { displayChoice } from './displayChoice'

/** Scales every rem-based size (text and the spacing around it) via the root font size;
 * see index.css. Images and thumbnails keep their size, unlike browser zoom. */
export type TextSize = 'small' | 'default' | 'large' | 'larger'
export const TEXT_SIZES: readonly { value: TextSize; label: string; title: string }[] = [
  { value: 'small', label: 'Small', title: 'Smaller text, denser layout' },
  { value: 'default', label: 'Default', title: 'Default text size' },
  { value: 'large', label: 'Large', title: 'Larger text' },
  { value: 'larger', label: 'Larger', title: 'Largest text' },
]

export const TEXT_SIZE_STORAGE_KEY = 'scene-atlas-text-size'

export const textSizeChoice = displayChoice<TextSize>(
  TEXT_SIZE_STORAGE_KEY,
  'textSize',
  TEXT_SIZES.map((t) => t.value),
  'default',
)

export const getStoredTextSize = textSizeChoice.read
export const applyTextSize = textSizeChoice.apply
