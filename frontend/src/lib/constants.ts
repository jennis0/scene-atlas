// Gallery / image grid layout
export const IMAGE_SIZE = 240
export const CARD_HEIGHT = 180
export const GRID_GAP = 16
export const GRID_PADDING = 16

// Relevance / search scoring
// Scores are RRF (Reciprocal Rank Fusion) combining text + semantic relevance.
// Max possible ≈ 2.6/60 ≈ 0.043 (rank 0 in all three lists). Set ceiling at
// 0.05 for headroom. In single-signal modes (semantic-only, text-only fallback)
// the top result scores ~0.017, reaching ~35% on the slider.
export const RELEVANCE_MIN = 0
export const RELEVANCE_MAX = 0.05
export const RELEVANCE_STEP = 0.001

/**
 * Convert a raw RRF min-score to a human-readable percentage.
 * The scale maps 0 (= 0%) to 0.05 (= 100%) linearly.
 */
export function relevanceToPercent(minScore: number): number {
  return Math.round(((minScore - RELEVANCE_MIN) / (RELEVANCE_MAX - RELEVANCE_MIN)) * 100)
}

// Polling
export const ACTIVE_POLL_INTERVAL_MS = 10_000
export const IDLE_POLL_INTERVAL_MS = 60_000
export const SAVED_INDICATOR_DURATION_MS = 1_500

// Input length limits
export const MAX_AUTHOR_LENGTH = 256
export const MAX_NAME_LENGTH = 512
export const MAX_SEARCH_LENGTH = 2048
