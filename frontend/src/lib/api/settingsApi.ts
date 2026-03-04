import { api } from './_client'
import type { AppSettings } from '@/types'

export const settingsApi = {
  get: async (): Promise<AppSettings> => {
    const { data } = await api.get<AppSettings>('/settings/')
    return data
  },
  patch: async (patch: Partial<AppSettings>): Promise<AppSettings> => {
    const { data } = await api.patch<AppSettings>('/settings/', patch)
    return data
  },
}
