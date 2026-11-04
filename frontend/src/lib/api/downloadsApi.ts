import { api } from './_client'

/** The groups and images a download holds (design/export-backup-move.md §5) */
export interface DownloadSelection {
  group_ids?: number[]
  image_ids?: number[]
}

export interface DownloadCheck {
  image_count: number
  bytes: number
  /** Images whose file can't be read: left out */
  missing: number
  ok: boolean
  reason: string | null
}

export const downloadsApi = {
  /** How big a download would be, and whether it's allowed (at most 999 files and 2 GB) */
  check: async (selection: DownloadSelection): Promise<DownloadCheck> => {
    const { data } = await api.post<DownloadCheck>('/downloads/check', selection)
    return data
  },
}
