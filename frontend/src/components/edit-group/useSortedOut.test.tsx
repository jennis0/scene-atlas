import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import {
  counts,
  idleQueue,
  installFakeImportManager,
  item,
  jobSummary,
  uninstallFakeImportManager,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import { useSortedOut } from './useSortedOut'

let manager: ImportManager | undefined
afterEach(() => {
  if (manager) uninstallFakeImportManager(manager)
  manager = undefined
})

const running = jobSummary({ status: 'active', counts: counts({ ready: 1, done: 3 }) })
const finished = jobSummary({ status: 'completed', counts: counts({ done: 3, skipped: 1 }) })
const token = item({ id: 20, state: 'skipped', error_kind: 'sorted_out', has_preview: true })

describe('useSortedOut', () => {
  it('merges included images into their group once the import finishes', async () => {
    const fake = await installFakeImportManager({ jobs: [running] })
    manager = fake.manager
    const merge = vi.fn(async () => {})
    const { result } = renderHook(() => useSortedOut(true, merge))

    act(() => result.current.included(41, 2, ['job1']))
    expect(result.current.importing).toEqual({ 41: 2 })
    expect(merge).not.toHaveBeenCalled()

    fake.state.jobs = [{ ...running, status: 'completed', counts: counts({ done: 4 }) }]
    await act(() => fake.manager.refresh())
    await waitFor(() => expect(merge).toHaveBeenCalledWith([41]))
    expect(result.current.importing).toEqual({})
  })

  it('reads the counts when opened and again after an include', async () => {
    const fake = await installFakeImportManager({ jobs: [finished], items: [token] })
    manager = fake.manager
    const { result } = renderHook(() =>
      useSortedOut(
        true,
        vi.fn(async () => {}),
      ),
    )
    await waitFor(() => expect(result.current.counts).toEqual({ 41: 1 }))

    const included = await act(() => fake.manager.include([20]))
    act(() => result.current.included(41, included.affected, included.job_ids))
    await waitFor(() => expect(result.current.counts).toEqual({}))
  })

  it("doesn't merge on a poll that started before the include", async () => {
    const fake = await installFakeImportManager({ jobs: [finished], items: [token] })
    manager = fake.manager
    const merge = vi.fn(async () => {})
    const { result } = renderHook(() => useSortedOut(true, merge))

    // A poll is in flight with the job list from before the include: still completed
    let releaseStale = () => {}
    const before = { jobs: fake.state.jobs, queue: idleQueue, version: 50 }
    fake.client.list.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseStale = () => resolve({ data: before, etag: null })
        }),
    )
    const stale = fake.manager.refresh()
    const including = fake.manager.include([20])
    // It lands after the include has asked for a refresh
    setTimeout(() => releaseStale(), 0)
    const included = await act(() => including)
    await act(() => stale)
    expect(included.job_ids).toEqual(['job1'])

    act(() => result.current.included(41, included.affected, included.job_ids))
    await act(() => fake.manager.refresh()) // still importing
    expect(merge).not.toHaveBeenCalled()
    expect(result.current.importing).toEqual({ 41: 1 })

    fake.state.jobs = [finished]
    await act(() => fake.manager.refresh())
    await waitFor(() => expect(merge).toHaveBeenCalledWith([41]))
  })

  it('treats an import no longer listed as finished', async () => {
    const fake = await installFakeImportManager({ jobs: [running] })
    manager = fake.manager
    const merge = vi.fn(async () => {})
    const { result } = renderHook(() => useSortedOut(true, merge))

    act(() => result.current.included(41, 1, ['job1']))
    fake.state.jobs = [] // e.g. cleared from Activity elsewhere
    await act(() => fake.manager.refresh())
    await waitFor(() => expect(merge).toHaveBeenCalledWith([41]))
  })

  it('forgets pending includes when closed', async () => {
    const fake = await installFakeImportManager({ jobs: [running] })
    manager = fake.manager
    const merge = vi.fn(async () => {})
    const { result, rerender } = renderHook(({ open }) => useSortedOut(open, merge), {
      initialProps: { open: true },
    })
    act(() => result.current.included(41, 2, ['job1']))
    expect(result.current.importing).toEqual({ 41: 2 })

    rerender({ open: false })
    expect(result.current.importing).toEqual({})
    fake.state.jobs = [{ ...running, status: 'completed' }]
    await act(() => fake.manager.refresh())
    expect(merge).not.toHaveBeenCalled()
  })

  it('watches the imports only while includes are pending, and keeps its value between polls', async () => {
    const fake = await installFakeImportManager({ jobs: [running] })
    manager = fake.manager
    const subscribe = vi.spyOn(fake.manager, 'subscribe')
    const { result } = renderHook(() =>
      useSortedOut(
        true,
        vi.fn(async () => {}),
      ),
    )
    await waitFor(() => expect(fake.client.sortedOutCounts).toHaveBeenCalled())
    await act(async () => {}) // the counts land
    const value = result.current
    await act(() => fake.manager.refresh())
    expect(subscribe).not.toHaveBeenCalled()
    expect(result.current).toBe(value)

    act(() => result.current.included(41, 1, ['job1']))
    expect(subscribe).toHaveBeenCalled()
  })
})
