import { api } from './_client'
import type {
  BulkImageChanges,
  BulkImageEditResponse,
  Image,
  ImageScope,
  ImageScopeFacets,
  TagData,
} from '@/types'

export const imageApi = {
  /** Apply one change to many images in one request: by id, or a scope resolved on the server. */
  bulkEdit: async (
    target: { image_ids: number[] } | { scope: ImageScope },
    changes: BulkImageChanges,
    addTags: TagData[] = [],
  ): Promise<BulkImageEditResponse> => {
    const { data } = await api.post<BulkImageEditResponse>('/images/bulk-edit', {
      ...target,
      changes,
      add_tags: addTags,
    })
    return data
  },

  /** Undo a bulk edit by the id it returned. */
  bulkRestore: async (undoId: string): Promise<void> => {
    await api.post('/images/bulk-restore', { undo_id: undoId })
  },

  /** Counts of a scope's images by type, grid state, subgroup and tag. */
  facets: async (scope: ImageScope): Promise<ImageScopeFacets> => {
    const { data } = await api.post<ImageScopeFacets>('/images/facets', scope)
    return data
  },

  get: async (id: number): Promise<Image> => {
    const { data } = await api.get<Image>(`/images/${id}`)
    return data
  },

  getScenes: async (id: number): Promise<Image[]> => {
    const { data } = await api.get<Image[]>(`/images/${id}/scenes`)
    return data
  },

  getAuthors: async (): Promise<string[]> => {
    const { data } = await api.get<string[]>('/images/authors')
    return data
  },

  patch: async (
    id: number,
    payload: {
      name?: string
      subgroup?: string | null
      gridded?: boolean | null
      grid_width?: number | null
      grid_height?: number | null
      grid_type?: string | null
      image_type?: string
    },
  ): Promise<Image> => {
    const { data } = await api.patch<Image>(`/images/${id}`, payload)
    return data
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/images/${id}`)
  },
}
