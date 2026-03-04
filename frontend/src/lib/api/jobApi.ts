import { api } from './_client'
import type { BackgroundJob } from '@/types'

export const jobApi = {
  list: async (): Promise<BackgroundJob[]> => {
    const { data } = await api.get<BackgroundJob[]>('/jobs/')
    return data
  },

  get: async (jobId: string): Promise<BackgroundJob> => {
    const { data } = await api.get<BackgroundJob>(`/jobs/${jobId}`)
    return data
  },
}
