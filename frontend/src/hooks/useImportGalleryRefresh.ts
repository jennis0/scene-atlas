import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { QUERY_KEYS, refreshGalleryInPlace } from '@/lib/queryKeys'

/** Marks the element that scrolls the gallery results (ImageGrid, and the grouped view in Gallery) */
const RESULTS_SCROLLER_ATTR = 'data-results-scroller'

/** Scrolled less than this still counts as being at the top */
const TOP_SLACK_PX = 120

/** At most one refresh this often: each one is a full search */
export const IMPORT_REFRESH_INTERVAL_MS = 4000

function scrolledToTop(container: HTMLElement | null): boolean {
  const scroller = container?.querySelector(`[${RESULTS_SCROLLER_ATTR}]`)
  return !scroller || scroller.scrollTop <= TOP_SLACK_PX
}

/** The most recent time any of these imports was grouped, or null if none is */
export function latestGroupedAt(jobs: readonly { grouped_at: string | null }[]): string | null {
  let latest: string | null = null
  for (const { grouped_at: at } of jobs) {
    if (at !== null && (latest === null || Date.parse(at) > Date.parse(latest))) latest = at
  }
  return latest
}

interface Options {
  /** Holds the results grid, whichever view is showing */
  containerRef: RefObject<HTMLElement | null>
  /**
   * The listed imports' latest grouping (``latestGroupedAt``), undefined until the import list
   * has loaded. An import's images appear when it is grouped (ADR-028), so when this moves past
   * the latest seen the gallery is behind. The first value is only a baseline, and an older one
   * (an import dismissed or re-opened) changes nothing.
   */
  groupedAt: string | null | undefined
  /** Something on screen indexes into the results (the image viewer): hold updates */
  paused: boolean
  /** The welcome screen shows instead of results until the library has images */
  libraryEmpty: boolean
}

/**
 * Brings imported maps into the gallery without moving what the user is looking at.
 *
 * An import's images appear all at once, when its groups have been identified. The results
 * then refresh in the background (the grid is never cleared), once the user is scrolled to the
 * top and the image viewer is closed.
 */
export function useImportGalleryRefresh({
  containerRef,
  groupedAt,
  paused,
  libraryEmpty,
}: Options) {
  const queryClient = useQueryClient()
  const [behind, setBehind] = useState(false)
  const [atTop, setAtTop] = useState(true)
  // The latest grouping seen: undefined until there is a baseline, null if none yet
  const groupedMarkRef = useRef<string | null | undefined>(groupedAt)
  const lastRefreshAtRef = useRef(0)

  useEffect(() => {
    if (groupedAt === undefined) return
    const mark = groupedMarkRef.current
    if (mark === undefined) {
      groupedMarkRef.current = groupedAt // the first known value is the baseline
      return
    }
    if (groupedAt === null) return
    if (mark !== null && Date.parse(groupedAt) <= Date.parse(mark)) return
    groupedMarkRef.current = groupedAt
    setBehind(true)
  }, [groupedAt])

  const markFinished = useCallback(() => setBehind(true), [])

  // Scroll events don't bubble, so listen in the capture phase for whichever grid is showing
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const onScroll = () => setAtTop(scrolledToTop(container))
    container.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => container.removeEventListener('scroll', onScroll, { capture: true })
  }, [containerRef])

  useEffect(() => {
    if (!behind || paused) return
    // Read the scroller itself: atTop is only a re-run trigger, and a freshly shown grid
    // (another view, a new search) starts at the top without a scroll event
    if (!scrolledToTop(containerRef.current)) return
    const wait = Math.max(0, IMPORT_REFRESH_INTERVAL_MS - (Date.now() - lastRefreshAtRef.current))
    const timer = setTimeout(() => {
      lastRefreshAtRef.current = Date.now()
      setBehind(false)
      refreshGalleryInPlace(queryClient)
      if (libraryEmpty) queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
    }, wait)
    return () => clearTimeout(timer)
  }, [behind, paused, atTop, libraryEmpty, containerRef, queryClient])

  return { markFinished }
}
