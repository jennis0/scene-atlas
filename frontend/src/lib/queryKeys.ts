import type { InfiniteData, QueryClient } from '@tanstack/react-query'

/**
 * Centralized query key constants for React Query.
 *
 * Static keys (e.g. `search`, `groups`) double as **prefix keys** for
 * invalidation — React Query's `invalidateQueries` uses prefix matching,
 * so `{ queryKey: QUERY_KEYS.search }` invalidates both `['search']` and
 * `['search', { q: '...' }]`.  Factory functions (`scenes`, `image`,
 * `groupSearch`) produce parameterised keys for individual queries.
 */
export const QUERY_KEYS = {
  search: ['search'] as const,
  searchFacets: ['searchFacets'] as const,
  tagCategories: ['tagCategories'] as const,
  scenes: (id?: number) => (id != null ? (['scenes', id] as const) : (['scenes'] as const)),
  image: (id: number) => ['image', id] as const,
  groups: ['groups'] as const,
  /** Every group picker search, to invalidate them all */
  groupSearches: ['groupSearch'] as const,
  groupSearch: (query: string, excludeGroupId?: number | null, currentGroupName?: string) =>
    ['groupSearch', query, excludeGroupId, currentGroupName] as const,
  systemInfo: ['system-info'] as const,
  serverUpdates: ['system-updates'] as const,
  appSettings: ['app-settings'] as const,
  models: ['models'] as const,
  modelSetupStatus: ['models', 'setup-status'] as const,
  tagPacks: ['tag-packs'] as const,
  backgroundJobs: ['background-jobs'] as const,
  libraryStatus: ['library-status'] as const,
}

/** Invalidates all queries affected by changes to the scene library (add/edit/delete). */
export function invalidateGalleryQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
  queryClient.resetQueries({ queryKey: QUERY_KEYS.groups })
}

/** After maps leave the library: the gallery, the linked folder's counts and the library totals */
export function invalidateRemovedMapsQueries(queryClient: QueryClient) {
  invalidateGalleryQueries(queryClient)
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.libraryStatus })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.systemInfo })
}

/**
 * Brings the gallery results up to date without clearing what's on screen: they refetch in the
 * background and replace the old ones when they arrive. Grouped results keep only their first
 * page, so the refetch is one request and later pages load against the new order. A refetch
 * already running is left to finish rather than restarted, so a slow search still lands.
 */
export function refreshGalleryInPlace(queryClient: QueryClient) {
  queryClient.setQueriesData<InfiniteData<unknown>>({ queryKey: QUERY_KEYS.groups }, (data) =>
    data && data.pages.length > 1
      ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) }
      : data,
  )
  const keepRunning = { cancelRefetch: false }
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search }, keepRunning)
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.groups }, keepRunning)
}

/** Invalidates tag categories and search facets (after tag CRUD operations). */
export function invalidateTagQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.tagCategories })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
}
