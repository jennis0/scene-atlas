import type { QueryClient } from '@tanstack/react-query'

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
  groupSearch: (query: string, excludeGroupId?: number | null, currentGroupName?: string) =>
    ['groupSearch', query, excludeGroupId, currentGroupName] as const,
  systemInfo: ['system-info'] as const,
  appSettings: ['app-settings'] as const,
  models: ['models'] as const,
  modelSetupStatus: ['models', 'setup-status'] as const,
  tagPacks: ['tag-packs'] as const,
  backgroundJobs: ['background-jobs'] as const,
}

/** Invalidates all queries affected by changes to the scene library (add/edit/delete). */
export function invalidateGalleryQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
  queryClient.resetQueries({ queryKey: QUERY_KEYS.groups })
}

/** Invalidates tag categories and search facets (after tag CRUD operations). */
export function invalidateTagQueries(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.tagCategories })
  queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
}
