import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { QUERY_KEYS } from '@/lib/queryKeys'
import {
  IMPORT_REFRESH_INTERVAL_MS,
  latestGroupedAt,
  useImportGalleryRefresh,
} from './useImportGalleryRefresh'

const SEARCH_KEY = [...QUERY_KEYS.search, { sort_by: 'created_at' }]

interface Props {
  groupedAt: string | null | undefined
  paused: boolean
  libraryEmpty: boolean
}

function setup(initial: Partial<Props> = {}) {
  const client = new QueryClient()
  const container = document.createElement('main')
  const scroller = document.createElement('div')
  scroller.setAttribute('data-results-scroller', '')
  container.appendChild(scroller)
  document.body.appendChild(container)
  const containerRef = { current: container }

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const props: Props = { groupedAt: null, paused: false, libraryEmpty: false, ...initial }
  const hook = renderHook((p: Props) => useImportGalleryRefresh({ containerRef, ...p }), {
    initialProps: props,
    wrapper,
  })

  // Fresh, un-invalidated search results, as if just fetched
  const seed = () => {
    client.setQueryData(SEARCH_KEY, { images: [] })
    client.setQueryData(QUERY_KEYS.searchFacets, { total_images: 0 })
  }
  seed()

  return {
    refreshed: () => client.getQueryState(SEARCH_KEY)?.isInvalidated ?? false,
    facetsRefreshed: () => client.getQueryState(QUERY_KEYS.searchFacets)?.isInvalidated ?? false,
    seed,
    update: (patch: Partial<Props>) => {
      Object.assign(props, patch)
      hook.rerender({ ...props })
    },
    scrollTo: (top: number) =>
      act(() => {
        scroller.scrollTop = top
        scroller.dispatchEvent(new Event('scroll'))
      }),
    markFinished: () => act(() => hook.result.current.markFinished()),
    elapse: (ms = IMPORT_REFRESH_INTERVAL_MS) => act(() => vi.advanceTimersByTime(ms)),
  }
}

describe('useImportGalleryRefresh', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    document.body.replaceChildren()
  })

  it('refreshes in place when an import is grouped and the user is at the top', () => {
    const t = setup()
    t.update({ groupedAt: '2026-10-22T10:00:00' })
    t.elapse()
    expect(t.refreshed()).toBe(true)
    expect(t.facetsRefreshed()).toBe(false) // the library already had maps
  })

  it('does nothing until an import is grouped', () => {
    const t = setup()
    t.elapse(IMPORT_REFRESH_INTERVAL_MS * 3)
    expect(t.refreshed()).toBe(false)
  })

  it('refreshes when an import finishes', () => {
    const t = setup()
    t.markFinished()
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('refreshes at most once per interval', () => {
    const t = setup()
    t.update({ groupedAt: '2026-10-22T10:00:00' })
    t.elapse(0) // nothing to wait behind yet
    expect(t.refreshed()).toBe(true)

    t.seed()
    t.update({ groupedAt: '2026-10-22T10:00:01' })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS - 1)
    expect(t.refreshed()).toBe(false)
    t.elapse(1)
    expect(t.refreshed()).toBe(true)
  })

  it('waits while the user is scrolled down, then catches up at the top', () => {
    const t = setup()
    t.scrollTo(2000)
    t.update({ groupedAt: '2026-10-22T10:00:00' })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS * 3)
    expect(t.refreshed()).toBe(false)

    t.scrollTo(50)
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('holds updates while the image viewer is open', () => {
    const t = setup({ paused: true })
    t.update({ groupedAt: '2026-10-22T10:00:00' })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS * 3)
    expect(t.refreshed()).toBe(false)

    t.update({ paused: false })
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('replaces the welcome screen when the first maps are grouped', () => {
    const t = setup({ libraryEmpty: true })
    t.update({ groupedAt: '2026-10-22T10:00:00' })
    t.elapse()
    expect(t.facetsRefreshed()).toBe(true)
  })

  it('takes the first loaded grouping as a baseline, not as news', () => {
    const t = setup({ groupedAt: undefined }) // the import list hasn't loaded
    t.update({ groupedAt: '2026-10-22T10:00:00' }) // grouped before the gallery opened
    t.elapse()
    expect(t.refreshed()).toBe(false)

    t.update({ groupedAt: '2026-10-22T10:01:00' })
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('ignores a grouping time that goes back or is cleared', () => {
    const t = setup({ groupedAt: '2026-10-22T10:05:00' })
    t.update({ groupedAt: '2026-10-22T10:00:00' }) // the latest import was dismissed
    t.elapse()
    expect(t.refreshed()).toBe(false)
    t.update({ groupedAt: null }) // or re-opened, or left the list
    t.elapse()
    expect(t.refreshed()).toBe(false)
    t.update({ groupedAt: '2026-10-22T10:05:00' }) // seen already
    t.elapse()
    expect(t.refreshed()).toBe(false)
  })
})

describe('latestGroupedAt', () => {
  it('is the most recent grouping among the imports', () => {
    expect(latestGroupedAt([])).toBeNull()
    expect(latestGroupedAt([{ grouped_at: null }])).toBeNull()
    expect(
      latestGroupedAt([
        { grouped_at: '2026-10-22T09:00:00' },
        { grouped_at: null },
        { grouped_at: '2026-10-22T10:00:00' },
        { grouped_at: '2026-10-22T09:59:59.900000' },
      ]),
    ).toBe('2026-10-22T10:00:00')
  })
})
