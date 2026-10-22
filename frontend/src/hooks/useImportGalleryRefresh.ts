import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { QUERY_KEYS, refreshGalleryInPlace } from '@/lib/queryKeys'

/** Marks the element that scrolls the gallery results (ImageGrid, and the grouped view in Gallery) */
const RESULTS_SCROLLER_ATTR = 'data-results-scroller'

/** Scrolled less than this still counts as being at the top */
const TOP_SLACK_PX = 120

/** At most one refresh this often while an import runs: each one is a full search */
export const IMPORT_REFRESH_INTERVAL_MS = 4000

function scrolledToTop(container: HTMLElement | null): boolean {
  const scroller = container?.querySelector(`[${RESULTS_SCROLLER_ATTR}]`)
  return !scroller || scroller.scrollTop <= TOP_SLACK_PX
}

/** The most recent grouping refinement among these imports, or null if none is refined */
export function latestGroupingRefinement(
  jobs: readonly { grouping_refined_at: string | null }[],
): string | null {
  let latest: string | null = null
  for (const { grouping_refined_at: at } of jobs) {
    if (at !== null && (latest === null || Date.parse(at) > Date.parse(latest))) latest = at
  }
  return latest
}

interface Options {
  /** Holds the results grid, whichever view is showing */
  containerRef: RefObject<HTMLElement | null>
  /** Files imported so far by the listed imports; when it grows the gallery is behind */
  importedTotal: number
  /**
   * The listed imports' latest grouping refinement (``latestGroupingRefinement``), undefined
   * until the import list has loaded. Refinement merges an import's groups, so when it moves
   * past the latest seen the grouped results are behind. The first value is only a baseline,
   * and an older one (an import dismissed or re-opened) changes nothing.
   */
  groupingRefinedAt: string | null | undefined
  /** New maps land at the top of the results (newest first, no search text) */
  newestAtTop: boolean
  /** Something on screen indexes into the results (the image viewer): hold updates */
  paused: boolean
  /** The welcome screen shows instead of results until the library has images */
  libraryEmpty: boolean
}

/** What the gallery is missing: maps from a running import, or an import's final state */
type Behind = 'no' | 'importing' | 'finished'

/**
 * Brings imported maps into the gallery without moving what the user is looking at.
 *
 * The results refresh in the background (the grid is never cleared) and only while they're
 * scrolled to the top. While an import runs that also needs new maps to land at the top, so a
 * name sort or a search isn't reshuffled every few seconds; once an import finishes, being at
 * the top is enough. Anything else waits until the user is back at the top. A finished import
 * whose groups were refined (merged) afterwards counts as finishing again.
 */
export function useImportGalleryRefresh({
  containerRef,
  importedTotal,
  groupingRefinedAt,
  newestAtTop,
  paused,
  libraryEmpty,
}: Options) {
  const queryClient = useQueryClient()
  const [behind, setBehind] = useState<Behind>('no')
  const [atTop, setAtTop] = useState(true)
  const lastTotalRef = useRef(importedTotal)
  // The latest refinement seen: undefined until there is a baseline, null if none yet
  const refinedMarkRef = useRef<string | null | undefined>(groupingRefinedAt)
  const lastRefreshAtRef = useRef(0)

  useEffect(() => {
    const grew = importedTotal > lastTotalRef.current
    lastTotalRef.current = importedTotal
    if (grew) setBehind((b) => (b === 'finished' ? b : 'importing'))
  }, [importedTotal])

  useEffect(() => {
    if (groupingRefinedAt === undefined) return
    const mark = refinedMarkRef.current
    if (mark === undefined) {
      refinedMarkRef.current = groupingRefinedAt // the first known value is the baseline
      return
    }
    if (groupingRefinedAt === null) return
    if (mark !== null && Date.parse(groupingRefinedAt) <= Date.parse(mark)) return
    refinedMarkRef.current = groupingRefinedAt
    setBehind('finished')
  }, [groupingRefinedAt])

  const markFinished = useCallback(() => setBehind('finished'), [])

  // Scroll events don't bubble, so listen in the capture phase for whichever grid is showing
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const onScroll = () => setAtTop(scrolledToTop(container))
    container.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => container.removeEventListener('scroll', onScroll, { capture: true })
  }, [containerRef])

  useEffect(() => {
    if (behind === 'no' || paused) return
    if (behind === 'importing' && !newestAtTop && !libraryEmpty) return
    // Read the scroller itself: atTop is only a re-run trigger, and a freshly shown grid
    // (another view, a new search) starts at the top without a scroll event
    if (!scrolledToTop(containerRef.current)) return
    const wait = Math.max(0, IMPORT_REFRESH_INTERVAL_MS - (Date.now() - lastRefreshAtRef.current))
    const timer = setTimeout(() => {
      lastRefreshAtRef.current = Date.now()
      setBehind('no')
      refreshGalleryInPlace(queryClient)
      if (libraryEmpty) queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
    }, wait)
    return () => clearTimeout(timer)
  }, [behind, paused, newestAtTop, atTop, importedTotal, libraryEmpty, containerRef, queryClient])

  return { markFinished }
}
