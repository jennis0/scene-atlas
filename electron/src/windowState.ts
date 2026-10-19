// The main window's size, position and maximised state, kept in the desktop config so it
// opens as the user left it (design/electron.md#window-state). Node-only (no electron
// import) so it can be unit tested with `node --test`.

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export interface WindowState extends Rect {
  maximized: boolean
}

export interface OpenBounds {
  width: number
  height: number
  /** Absent: the OS places the window (centred) */
  x?: number
  y?: number
}

export const DEFAULT_SIZE = { width: 1400, height: 900 }
export const MIN_SIZE = { width: 900, height: 600 }
/** How much of a window's top edge must be on a screen for its saved position to be used:
 * enough to grab it there and move it. */
const GRAB = { width: 100, height: 20 }

const isInt = (value: unknown): value is number => Number.isInteger(value)
const isSize = (value: unknown): value is number => isInt(value) && value > 0

function asRecord(raw: unknown): Record<string, unknown> | null {
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : null
}

/** The saved state from the config, or null if it's missing or malformed. */
export function sanitizeWindowState(raw: unknown): WindowState | null {
  const record = asRecord(raw)
  if (!record) return null
  const { x, y, width, height, maximized } = record
  const valid =
    isInt(x) && isInt(y) && isSize(width) && isSize(height) && typeof maximized === 'boolean'
  return valid ? { x, y, width, height, maximized } : null
}

function overlap(a: Rect, b: Rect): { width: number; height: number } {
  return {
    width: Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x),
    height: Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y),
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, Math.max(min, max)))
}

/**
 * Where the main window opens. *workAreas* are the screens' work areas, the primary
 * first. The saved size is kept, at least the minimum and at most the screen it opens
 * on. The saved position is kept only if enough of the window's top edge is on a screen
 * to grab it: a monitor may have been unplugged since.
 */
export function restoredBounds(saved: WindowState | null, workAreas: Rect[]): OpenBounds {
  const screen = saved ? screenUnderTopEdge(saved, workAreas) : undefined
  const primary: Rect | undefined = workAreas[0]
  const size = fitTo(saved ?? DEFAULT_SIZE, screen ?? primary)
  return saved && screen ? { ...size, x: saved.x, y: saved.y } : size
}

/** The screen enough of the window's top edge is on to grab it there, if any. */
function screenUnderTopEdge(saved: WindowState, workAreas: Rect[]): Rect | undefined {
  const topEdge = { x: saved.x, y: saved.y, width: saved.width, height: GRAB.height }
  return workAreas.find((area) => {
    const shared = overlap(topEdge, area)
    return shared.width >= GRAB.width && shared.height >= GRAB.height
  })
}

/** *size*, at least the minimum and at most *area*; unchanged when no screen is known. */
function fitTo(size: { width: number; height: number }, area: Rect | undefined) {
  if (!area) return { width: size.width, height: size.height }
  return {
    width: clamp(size.width, MIN_SIZE.width, area.width),
    height: clamp(size.height, MIN_SIZE.height, area.height),
  }
}
