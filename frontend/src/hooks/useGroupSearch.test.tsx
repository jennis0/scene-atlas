import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { GroupSearchResult, Image } from '@/types'
import { useGroupSearch } from './useGroupSearch'

const mockGroups = vi.fn()

vi.mock('@/lib/api', () => ({
  searchApi: { groups: (...args: unknown[]) => mockGroups(...args) },
}))

const group = (id: number): GroupSearchResult => ({
  group_id: id,
  base_name: `Group ${id}`,
  author: null,
  hero_image: { id: id * 10, tags: [] } as unknown as Image,
  mosaic_images: [],
  total_scenes: 1,
  matching_scenes: 1,
  best_score: null,
})

describe('useGroupSearch', () => {
  it('keeps each group once when an import shifts the next page onto loaded groups', async () => {
    // Group 3 was imported after page one loaded, pushing group 2 onto page two
    mockGroups.mockImplementation(({ offset }: { offset: number }) =>
      Promise.resolve({
        total_groups: 100,
        limit: 50,
        offset,
        groups: offset === 0 ? [group(1), group(2)] : [group(2), group(4)],
      }),
    )
    const client = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useGroupSearch({}), { wrapper })
    await waitFor(() => expect(result.current.groups).toHaveLength(2))

    await act(() => result.current.fetchNextPage())

    await waitFor(() => expect(result.current.groups.map((g) => g.groupId)).toEqual([1, 2, 4]))
  })
})
