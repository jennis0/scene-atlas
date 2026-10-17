import { api } from './_client'
import type { BackgroundJob } from '@/types'

export const jobApi = {
  list: async (): Promise<BackgroundJob[]> => {
    const { data } = await api.get<BackgroundJob[]>('/jobs/')
    return data
  },

  /** Remove a finished job from the activity dock */
  dismiss: async (jobId: string): Promise<void> => {
    await api.post(`/jobs/${jobId}/dismiss`)
  },

  /** Remove every finished job from the activity dock */
  dismissFinished: async (): Promise<void> => {
    await api.post('/jobs/dismiss-finished')
  },

  get: async (jobId: string): Promise<BackgroundJob> => {
    const { data } = await api.get<BackgroundJob>(`/jobs/${jobId}`)
    return data
  },
}
