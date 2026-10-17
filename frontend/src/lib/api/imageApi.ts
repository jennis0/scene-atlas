import { api } from './_client'
import type { Image } from '@/types'

export const imageApi = {
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
