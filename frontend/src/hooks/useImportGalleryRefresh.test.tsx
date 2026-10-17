import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { QUERY_KEYS } from '@/lib/queryKeys'
import { IMPORT_REFRESH_INTERVAL_MS, useImportGalleryRefresh } from './useImportGalleryRefresh'

const SEARCH_KEY = [...QUERY_KEYS.search, { sort_by: 'created_at' }]

interface Props {
  importedTotal: number
  newestAtTop: boolean
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
  const props: Props = {
    importedTotal: 0,
    newestAtTop: true,
    paused: false,
    libraryEmpty: false,
    ...initial,
  }
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

  it('refreshes in place when maps are imported and the user is at the top', () => {
    const t = setup()
    t.update({ importedTotal: 3 })
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('does nothing until something is imported', () => {
    const t = setup({ importedTotal: 5 })
    t.elapse()
    expect(t.refreshed()).toBe(false)
  })

  it('refreshes at most once per interval while the count keeps growing', () => {
    const t = setup()
    t.update({ importedTotal: 1 })
    t.elapse(0) // nothing to wait behind yet
    expect(t.refreshed()).toBe(true)

    t.seed()
    t.update({ importedTotal: 2 })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS / 2)
    t.update({ importedTotal: 3 })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS / 2 - 1)
    expect(t.refreshed()).toBe(false)
    t.elapse(1)
    expect(t.refreshed()).toBe(true)
  })

  it('waits while the user is scrolled down, then catches up at the top', () => {
    const t = setup()
    t.scrollTo(2000)
    t.update({ importedTotal: 4 })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS * 3)
    expect(t.refreshed()).toBe(false)

    t.scrollTo(0)
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('does not reshuffle a name sort or a search while importing, but does once finished', () => {
    const t = setup({ newestAtTop: false })
    t.update({ importedTotal: 4 })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS * 3)
    expect(t.refreshed()).toBe(false)

    t.markFinished()
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('a finished import still waits for the user to be at the top', () => {
    const t = setup()
    t.scrollTo(2000)
    t.markFinished()
    t.elapse()
    expect(t.refreshed()).toBe(false)

    t.scrollTo(50)
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('holds updates while the image viewer is open', () => {
    const t = setup({ paused: true })
    t.update({ importedTotal: 2 })
    t.elapse(IMPORT_REFRESH_INTERVAL_MS * 3)
    expect(t.refreshed()).toBe(false)

    t.update({ paused: false })
    t.elapse()
    expect(t.refreshed()).toBe(true)
  })

  it('replaces the welcome screen as soon as the first maps arrive, whatever the sort', () => {
    const t = setup({ newestAtTop: false, libraryEmpty: true })
    t.update({ importedTotal: 1 })
    t.elapse()
    expect(t.facetsRefreshed()).toBe(true)
  })

  it('leaves the facets alone once the library has maps', () => {
    const t = setup()
    t.update({ importedTotal: 1 })
    t.elapse()
    expect(t.refreshed()).toBe(true)
    expect(t.facetsRefreshed()).toBe(false)
  })
})
