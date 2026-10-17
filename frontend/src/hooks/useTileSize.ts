import { useCallback, useState } from 'react'
import { TILE_SIZES, type TileSize } from '@/lib/constants'

const STORAGE_KEY = 'gallery-tile-size'

function load(): TileSize {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored && stored in TILE_SIZES ? (stored as TileSize) : 'medium'
  } catch {
    return 'medium'
  }
}

/** The individual view's tile size, remembered on this device. */
export function useTileSize() {
  const [tileSize, setState] = useState<TileSize>(load)
  const setTileSize = useCallback((size: TileSize) => {
    setState(size)
    try {
      localStorage.setItem(STORAGE_KEY, size)
    } catch {
      // Storage blocked: the size still applies for this session.
    }
  }, [])
  return { tileSize, setTileSize }
}
