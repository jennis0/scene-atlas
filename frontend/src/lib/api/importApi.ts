import { api } from './_client'
import { BATCH_UPLOAD_TIMEOUT_MS } from '@/lib/constants'
import type { AxiosProgressEvent } from 'axios'
import type {
  ImportUploadResponse,
  BatchUploadResponse,
  ImportConfirmRequest,
  ImportJobResponse,
  ActiveImportsResponse,
  HashCheckItem,
  HashCheckResponse,
  DuplicateInfo,
} from '@/types'

export const importApi = {
  init: async (): Promise<{ job_id: string }> => {
    const { data } = await api.post<{ job_id: string }>('/imports/init')
    return data
  },

  checkHashes: async (files: HashCheckItem[]): Promise<HashCheckResponse> => {
    const { data } = await api.post<HashCheckResponse>('/imports/check-hashes', { files })
    return data
  },

  uploadBatch: async (
    jobId: string,
    files: File[],
    relativePaths: string[],
    onUploadProgress?: (event: AxiosProgressEvent) => void,
  ): Promise<BatchUploadResponse> => {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    if (relativePaths.length > 0) {
      formData.append('relative_paths', JSON.stringify(relativePaths))
    }
    const { data } = await api.post<BatchUploadResponse>(
      `/imports/${jobId}/upload-batch`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: BATCH_UPLOAD_TIMEOUT_MS,
        onUploadProgress,
      },
    )
    return data
  },

  analyse: async (
    jobId: string,
    manifest?: Array<{
      relative_path: string
      filename: string
      content_hash: string
      duplicate_of: DuplicateInfo
    }>,
    imageType?: string,
  ): Promise<ImportUploadResponse> => {
    const { data } = await api.post<ImportUploadResponse>(
      `/imports/${jobId}/analyse`,
      { manifest: manifest ?? [], image_type: imageType ?? 'battlemap' },
      { timeout: 120_000 },
    )
    return data
  },

  confirmAll: async (jobId: string, groups: ImportConfirmRequest[]): Promise<ImportJobResponse> => {
    const { data } = await api.post<ImportJobResponse>(`/imports/${jobId}/confirm-all`, { groups })
    return data
  },

  status: async (jobId: string): Promise<ImportJobResponse> => {
    const { data } = await api.get<ImportJobResponse>(`/imports/${jobId}/status`)
    return data
  },

  getAnalysis: async (jobId: string): Promise<ImportUploadResponse> => {
    const { data } = await api.get<ImportUploadResponse>(`/imports/${jobId}/analysis`)
    return data
  },

  active: async (): Promise<ActiveImportsResponse> => {
    const { data } = await api.get<ActiveImportsResponse>('/imports/active')
    return data
  },

  cancel: async (jobId: string): Promise<void> => {
    await api.post(`/imports/${jobId}/cancel`)
  },

  fail: async (jobId: string, errorMessage: string): Promise<void> => {
    await api.post(`/imports/${jobId}/fail`, { error_message: errorMessage })
  },

  cancelGroup: async (jobId: string, groupId: string): Promise<void> => {
    await api.post(`/imports/${jobId}/groups/${groupId}/cancel`)
  },

  reportSkipped: async (
    jobId: string,
    files: Array<{ filename: string; reason: string }>,
  ): Promise<void> => {
    await api.post(`/imports/${jobId}/report-skipped`, { files })
  },

  cleanup: async (): Promise<{ deleted: number }> => {
    const { data } = await api.delete<{ deleted: number }>('/imports/cleanup')
    return data
  },
}
