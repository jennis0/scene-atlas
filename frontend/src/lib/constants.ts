// ── Gallery / image grid layout ─────────────────────────────────────────────
export const IMAGE_SIZE = 240
export const CARD_HEIGHT = 180
export const GRID_GAP = 16
export const GRID_PADDING = 16

// ── Relevance / semantic search ──────────────────────────────────────────────
export const RELEVANCE_MIN = 0.1
export const RELEVANCE_MAX = 0.5
export const RELEVANCE_STEP = 0.01

/**
 * Convert a raw semantic similarity min-score to a human-readable percentage.
 * The scale maps 0.1 (= 0%) to 0.5 (= 100%) linearly.
 */
export function relevanceToPercent(minScore: number): number {
  return Math.round(((minScore - RELEVANCE_MIN) / (RELEVANCE_MAX - RELEVANCE_MIN)) * 100)
}

// ── Import workflow timings ──────────────────────────────────────────────────
export const POLL_INTERVAL_MS = 2_000
export const ACTIVE_POLL_INTERVAL_MS = 10_000
export const AUTO_SAVE_INTERVAL_MS = 60_000
export const SAVED_INDICATOR_DURATION_MS = 1_500
export const IMPORT_STORAGE_EXPIRY_MS = 24 * 60 * 60 * 1_000 // 24 hours

// ── Upload limits ────────────────────────────────────────────────────────────
export const MAX_FILE_SIZE_MB = 200
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

// ── Batch upload ─────────────────────────────────────────────────────────────
export const MAX_BATCH_FILES = 20
export const MAX_BATCH_BYTES = 100 * 1024 * 1024 // 100 MB per batch
export const BATCH_UPLOAD_TIMEOUT_MS = 5 * 60 * 1000 // 5 minutes per batch
export const MAX_BATCH_RETRIES = 2

// ── Input length limits ──────────────────────────────────────────────────────
export const MAX_AUTHOR_LENGTH = 256
export const MAX_NAME_LENGTH = 512
export const MAX_SEARCH_LENGTH = 2048

// ── Canvas / image viewer ────────────────────────────────────────────────────
export const CANVAS_DOT_SIZE = 24
