import { api } from './_client'

export const systemApi = {
  getInfo: async <T = unknown>(): Promise<T> => {
    const { data } = await api.get<T>('/system/info')
    return data
  },

  deleteLibrary: async (): Promise<{ job_id: string; message: string }> => {
    const { data } = await api.delete<{ job_id: string; message: string }>('/system/library')
    return data
  },

  resetTags: async (): Promise<{
    deleted_tags: number
    deleted_categories: number
    seeded_categories: number
  }> => {
    const { data } = await api.post('/system/tags/reset')
    return data
  },
}
