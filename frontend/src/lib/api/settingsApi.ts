import { api } from './_client'
import type { AppSettings } from '@/types'

export const settingsApi = {
  get: async (): Promise<AppSettings> => {
    const { data } = await api.get('/settings/')
    return data
  },
  patch: async (patch: Partial<AppSettings>): Promise<AppSettings> => {
    const { data } = await api.patch('/settings/', patch)
    return data
  },
}
