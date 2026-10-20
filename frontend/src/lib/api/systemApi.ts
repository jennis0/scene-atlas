import { api } from './_client'

/** The server's last check for a newer release (GET /system/updates, server mode). The
 * backend checks once a day; fetching this never makes it check. */
export interface ServerUpdateStatus {
  /** 'disabled': the admin turned checks off (or the desktop app); 'pending': no check
   * has succeeded yet; 'unknown': the running version isn't a release build */
  status: 'disabled' | 'pending' | 'up_to_date' | 'available' | 'unknown'
  current_version: string
  checks_enabled: boolean
  latest_version: string | null
  update_available: boolean
  /** The latest release's page, or the releases list */
  release_url: string
  last_checked: string | null
}

export const systemApi = {
  getInfo: async <T = unknown>(): Promise<T> => {
    const { data } = await api.get<T>('/system/info')
    return data
  },

  getUpdates: async (): Promise<ServerUpdateStatus> => {
    const { data } = await api.get<ServerUpdateStatus>('/system/updates')
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
