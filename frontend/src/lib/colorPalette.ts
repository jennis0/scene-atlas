export interface PaletteColor {
  hex: string
  label: string
}

/** Curated palette of battlemap-typical colors for the color filter. */
export const COLOR_FILTER_PALETTE: PaletteColor[] = [
  // Row 1 — Greens
  { hex: '#0a1f0a', label: 'Dark Green' },
  { hex: '#1a3a1a', label: 'Dark Forest' },
  { hex: '#2d5a27', label: 'Forest' },
  { hex: '#4a7c3f', label: 'Grass' },
  { hex: '#3b6b4a', label: 'Swamp' },
  { hex: '#7ab648', label: 'Lime' },

  // Row 2 — Blues & Cyan
  { hex: '#0a1628', label: 'Abyss' },
  { hex: '#1a3a5c', label: 'Deep Water' },
  { hex: '#3a7ca5', label: 'Water' },
  { hex: '#87ceeb', label: 'Sky' },
  { hex: '#1a8a8a', label: 'Teal' },
  { hex: '#40e0d0', label: 'Cyan' },

  // Row 3 — Browns & Tan
  { hex: '#3a2010', label: 'Dark Wood' },
  { hex: '#5c3a1e', label: 'Earth' },
  { hex: '#8b6914', label: 'Wood' },
  { hex: '#c2a64e', label: 'Sand' },
  { hex: '#d4b483', label: 'Parchment' },
  { hex: '#f5deb3', label: 'Wheat' },

  // Row 4 — Reds & Warm
  { hex: '#4a0a0a', label: 'Dark Red' },
  { hex: '#8b1a1a', label: 'Blood' },
  { hex: '#cc4400', label: 'Fire' },
  { hex: '#e8a040', label: 'Sunset' },
  { hex: '#e8c840', label: 'Gold' },
  { hex: '#e85080', label: 'Pink' },

  // Row 5 — Purples & Fey
  { hex: '#2a1a3a', label: 'Shadow' },
  { hex: '#4a1a6a', label: 'Arcane' },
  { hex: '#6a2c8a', label: 'Fey' },
  { hex: '#9a50c8', label: 'Violet' },
  { hex: '#1a1a2e', label: 'Night' },
  { hex: '#0a0a14', label: 'Void' },

  // Row 6 — Grays & Neutrals
  { hex: '#2a2a2a', label: 'Dark Stone' },
  { hex: '#5a5a5a', label: 'Stone' },
  { hex: '#909090', label: 'Light Stone' },
  { hex: '#b8d4e8', label: 'Ice' },
  { hex: '#e8e8e8', label: 'Snow' },
  { hex: '#f8f8f8', label: 'White' },
]
