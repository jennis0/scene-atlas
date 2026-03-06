import { api } from './_client'
import type { SearchResult, SearchParams, FacetData, GroupSearchResponse } from '@/types'

export const searchApi = {
  search: async (params: SearchParams): Promise<SearchResult> => {
    const { data } = await api.get<SearchResult>('/search/', { params })
    return data
  },

  groups: async (
    params: SearchParams & { limit?: number; offset?: number },
  ): Promise<GroupSearchResponse> => {
    const { data } = await api.get<GroupSearchResponse>('/search/groups', { params })
    return data
  },

  facets: async (): Promise<FacetData> => {
    const { data } = await api.get<FacetData>('/search/facets')
    return data
  },
}
