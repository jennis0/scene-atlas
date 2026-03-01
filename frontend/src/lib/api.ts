import axios from 'axios'
import { getApiBaseUrl, resolveApiUrl } from './apiBase'
import type {
  Image,
  Tag,
  SearchResult,
  SearchParams,
  FacetData,
  TagCategory,
  TagValue,
  TagStats,
  ImportUploadResponse,
  BatchUploadResponse,
  ImportConfirmRequest,
  ImportJobResponse,
  ActiveImportsResponse,
  GroupDetail,
  GroupEditRequest,
  GroupEditResponse,
  GroupSearchResponse,
  GroupMergeResponse,
  MoveImagesResponse,
  HashCheckItem,
  HashCheckResponse,
  DuplicateInfo,
  BackgroundJob,
  AppSettings,
} from '@/types'
import type { AxiosProgressEvent } from 'axios'
import {
  BATCH_UPLOAD_TIMEOUT_MS,
} from '@/lib/constants'

const api = axios.create({
  timeout: 30000,
  paramsSerializer: {
    indexes: null, // Format arrays as: ?tags=a&tags=b (no brackets)
  },
})

// Resolve base URL at request time (not import time) so the port injected
// by Electron's preload script is picked up after backend becomes ready.
api.interceptors.request.use((config) => {
  if (!config.baseURL) {
    config.baseURL = getApiBaseUrl()
  }
  return config
})

export const imageApi = {
  list: async (limit = 100, offset = 0): Promise<Image[]> => {
    const { data } = await api.get<Image[]>('/images/', { params: { limit, offset } })
    return data
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

export const searchApi = {
  search: async (params: SearchParams): Promise<SearchResult> => {
    const { data } = await api.get<SearchResult>('/search/', { params })
    return data
  },

  facets: async (): Promise<FacetData> => {
    const { data } = await api.get<FacetData>('/search/facets')
    return data
  },
}

export const tagApi = {
  // ── Category CRUD ──────────────────────────────────────────────────────

  getCategories: async (): Promise<TagCategory[]> => {
    const { data } = await api.get<TagCategory[]>('/tags/categories')
    return data
  },

  getCategory: async (category: string): Promise<TagCategory> => {
    const { data } = await api.get<TagCategory>(`/tags/categories/${category}`)
    return data
  },

  createCategory: async (payload: {
    name: string
    description?: string
    color?: string
    icon?: string | null
    display_order?: number
  }): Promise<TagCategory> => {
    const { data } = await api.post<TagCategory>('/tags/categories', payload)
    return data
  },

  updateCategory: async (
    categoryName: string,
    payload: {
      name?: string
      description?: string
      color?: string
      icon?: string | null
      display_order?: number
    },
  ): Promise<{ category: TagCategory; affected_images: number }> => {
    const { data } = await api.patch(`/tags/categories/${categoryName}`, payload)
    return data
  },

  deleteCategory: async (
    categoryName: string,
  ): Promise<{ deleted_tags: number; affected_images: number }> => {
    const { data } = await api.delete(`/tags/categories/${categoryName}`)
    return data
  },

  // ── Tag value management within categories ─────────────────────────────

  upsertTagValue: async (
    categoryName: string,
    tagName: string,
    aliases?: string[],
  ): Promise<TagCategory> => {
    const { data } = await api.put<TagCategory>(
      `/tags/categories/${categoryName}/tags/${tagName}`,
      aliases ?? [],
    )
    return data
  },

  renameTagValue: async (
    categoryName: string,
    tagName: string,
    newValue: string,
  ): Promise<{
    category: TagCategory
    old_value: string
    new_value: string
    affected_images: number
  }> => {
    const { data } = await api.patch(`/tags/categories/${categoryName}/tags/${tagName}`, {
      new_value: newValue,
    })
    return data
  },

  deleteTagValue: async (
    categoryName: string,
    tagName: string,
  ): Promise<{ deleted_tags: number; affected_images: number }> => {
    const { data } = await api.delete(`/tags/categories/${categoryName}/tags/${tagName}`)
    return data
  },

  // ── Per-image tag operations ───────────────────────────────────────────

  getValues: async (category: string): Promise<TagValue[]> => {
    const { data } = await api.get<TagValue[]>(`/tags/values/${category}`)
    return data
  },

  getStats: async (): Promise<TagStats> => {
    const { data } = await api.get<TagStats>('/tags/stats')
    return data
  },

  addToImage: async (imageId: number, tag: { category: string; value: string }): Promise<Tag> => {
    const { data } = await api.post<Tag>(`/tags/image/${imageId}`, {
      ...tag,
      confidence: 1.0,
      source: 'manual',
    })
    return data
  },

  removeTag: async (tagId: number): Promise<void> => {
    await api.delete(`/tags/${tagId}`)
  },

  retagAll: async (): Promise<{ job_id: string; message: string }> => {
    const { data } = await api.post('/tags/retag-all')
    return data
  },
}

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

  confirm: async (jobId: string, group: ImportConfirmRequest): Promise<ImportJobResponse> => {
    const { data } = await api.post<ImportJobResponse>(`/imports/${jobId}/confirm`, group)
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

  finalize: async (
    jobId: string,
  ): Promise<{ status: string; staging_cleaned: boolean; already_terminal: boolean }> => {
    const { data } = await api.post<{
      status: string
      staging_cleaned: boolean
      already_terminal: boolean
    }>(`/imports/${jobId}/finalize`)
    return data
  },

  cancel: async (jobId: string): Promise<void> => {
    await api.post(`/imports/${jobId}/cancel`)
  },

  cancelGroup: async (jobId: string, groupId: string): Promise<void> => {
    await api.post(`/imports/${jobId}/groups/${groupId}/cancel`)
  },

  cleanup: async (): Promise<{ deleted: number }> => {
    const { data } = await api.delete<{ deleted: number }>('/imports/cleanup')
    return data
  },
}

export const groupApi = {
  get: async (id: number): Promise<GroupDetail> => {
    const { data } = await api.get<GroupDetail>(`/groups/${id}`)
    return data
  },

  edit: async (id: number, payload: GroupEditRequest): Promise<GroupEditResponse> => {
    const { data } = await api.put<GroupEditResponse>(`/groups/${id}`, payload)
    return data
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/groups/${id}`)
  },

  search: async (
    q: string,
    excludeId?: number,
    limit = 20,
    referenceName?: string,
  ): Promise<GroupSearchResponse> => {
    const { data } = await api.get<GroupSearchResponse>('/groups/search', {
      params: {
        q,
        exclude_id: excludeId,
        limit,
        ...(referenceName ? { reference_name: referenceName } : {}),
      },
    })
    return data
  },

  merge: async (sourceId: number, targetGroupId: number): Promise<GroupMergeResponse> => {
    const { data } = await api.post<GroupMergeResponse>(`/groups/${sourceId}/merge`, {
      target_group_id: targetGroupId,
    })
    return data
  },

  moveImages: async (
    sourceGroupId: number,
    targetGroupId: number,
    imageIds: number[],
  ): Promise<MoveImagesResponse> => {
    const { data } = await api.post<MoveImagesResponse>(`/groups/${sourceGroupId}/move-images`, {
      target_group_id: targetGroupId,
      image_ids: imageIds,
    })
    return data
  },
}

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

export const getThumbnailUrl = (image: Image): string =>
  resolveApiUrl(`/api/v1/images/${image.id}/thumbnail`)

export const getThumbnailUrlById = (id: number): string =>
  resolveApiUrl(`/api/v1/images/${id}/thumbnail`)

export const getImageUrl = (image: Image): string =>
  resolveApiUrl(`/api/v1/images/${image.id}/file`)

export const getGroupDownloadUrl = (groupId: number): string =>
  resolveApiUrl(`/api/v1/groups/${groupId}/download`)

export const getLibraryExportUrl = (): string => resolveApiUrl('/api/v1/export/library')

export const getImageUrlById = (id: number): string => resolveApiUrl(`/api/v1/images/${id}/file`)

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
