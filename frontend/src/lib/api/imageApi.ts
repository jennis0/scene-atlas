import { api } from './_client'
import type {
  BulkImageChanges,
  BulkImageEditResponse,
  Image,
  ImageRestoreState,
  TagData,
} from '@/types'

export const imageApi = {
  /** Apply one change to many images in one request; the response is what undo needs. */
  bulkEdit: async (
    imageIds: number[],
    changes: BulkImageChanges,
    addTags: TagData[] = [],
  ): Promise<BulkImageEditResponse> => {
    const { data } = await api.post<BulkImageEditResponse>('/images/bulk-edit', {
      image_ids: imageIds,
      changes,
      add_tags: addTags,
    })
    return data
  },

  /** Undo a bulk edit: its previous states, and the tags it added. */
  bulkRestore: async (images: ImageRestoreState[], removeTagIds: number[]): Promise<void> => {
    await api.post('/images/bulk-restore', { images, remove_tag_ids: removeTagIds })
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
