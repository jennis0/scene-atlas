import { useCallback, useState } from 'react'
import { TILE_WIDTH } from '@/lib/constants'

const STORAGE_KEY = 'gallery-tile-width'

function clamp(width: number): number {
  const stepped = Math.round(width / TILE_WIDTH.step) * TILE_WIDTH.step
  return Math.min(TILE_WIDTH.max, Math.max(TILE_WIDTH.min, stepped))
}

function load(): number {
  try {
    const stored = Number(localStorage.getItem(STORAGE_KEY))
    return stored ? clamp(stored) : TILE_WIDTH.default
  } catch {
    return TILE_WIDTH.default
  }
}

/** The individual view's tile width in px, remembered on this device. */
export function useTileSize() {
  const [tileWidth, setState] = useState<number>(load)
  const setTileWidth = useCallback((width: number) => {
    const next = clamp(width)
    setState(next)
    try {
      localStorage.setItem(STORAGE_KEY, String(next))
    } catch {
      // Storage blocked: the size still applies for this session.
    }
  }, [])
  return { tileWidth, setTileWidth }
}
