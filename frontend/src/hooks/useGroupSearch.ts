import { useMemo, useCallback } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { searchApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import type { GroupSearchResult, GroupSearchResponse, ImageGroup, SearchParams } from '@/types'

const PAGE_SIZE = 50

/**
 * Transforms a GroupSearchResult (from API) to an ImageGroup (client-side type).
 * Synthesises aggregatedTags from hero + mosaic images (partial coverage).
 */
function toImageGroup(result: GroupSearchResult): ImageGroup {
  const allTags = [result.hero_image, ...result.mosaic_images].flatMap((img) => img.tags ?? [])
  const seen = new Set<string>()
  const aggregatedTags = allTags.filter((t) => {
    const key = `${t.category}:${t.value}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  return {
    groupId: result.group_id,
    baseName: result.base_name,
    author: result.author ?? '',
    heroImage: result.hero_image,
    mosaicImages: result.mosaic_images,
    totalScenes: result.total_scenes,
    matchingCount: result.matching_scenes,
    bestScore: result.best_score,
    aggregatedTags,
  }
}

/**
 * Paged group search for infinite scroll. Groups below `minScore` are dropped client-side;
 * groups with a null bestScore (no query, so nothing to score) are always kept.
 */
export function useGroupSearch(
  params: Omit<SearchParams, 'limit' | 'offset'>,
  minScore: number = 0,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const queryClient = useQueryClient()
  const queryKey = useMemo(() => [...QUERY_KEYS.groups, params], [params])

  const query = useInfiniteQuery<GroupSearchResponse>({
    queryKey,
    enabled,
    queryFn: ({ pageParam = 0 }) =>
      searchApi.groups({ ...params, limit: PAGE_SIZE, offset: pageParam as number }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const fetched = (lastPage.offset ?? 0) + PAGE_SIZE
      return fetched < lastPage.total_groups ? fetched : undefined
    },
  })

  const groups = useMemo(
    () =>
      query.data?.pages
        .flatMap((p) => p.groups)
        .map(toImageGroup)
        .filter((g) => g.bestScore === null || g.bestScore >= minScore) ?? [],
    [query.data?.pages, minScore],
  )

  const totalGroups = query.data?.pages[0]?.total_groups ?? 0

  // Removing (not refetching) drops the loaded pages, so the next fetch restarts at offset 0.
  const reset = useCallback(() => {
    queryClient.removeQueries({ queryKey })
  }, [queryClient, queryKey])

  return {
    ...query,
    groups,
    totalGroups,
    reset,
  }
}
