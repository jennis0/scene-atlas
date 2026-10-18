import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import {
  counts,
  installFakeImportManager,
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

describe('useSortedOut', () => {
  it('merges included images into their group once the import finishes', async () => {
    const running = jobSummary({ status: 'active', counts: counts({ ready: 1, done: 3 }) })
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
})
