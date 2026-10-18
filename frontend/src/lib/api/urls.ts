import type { ImportItem } from '@/lib/import/types'
import type { Image } from '@/types'

export const getThumbnailUrl = (image: Image): string => `/api/v1/images/${image.id}/thumbnail`

export const getThumbnailUrlById = (id: number): string => `/api/v1/images/${id}/thumbnail`

export const getImageUrl = (image: Image): string => `/api/v1/images/${image.id}/file`

export const getImageUrlById = (id: number): string => `/api/v1/images/${id}/file`

export const getGroupDownloadUrl = (groupId: number): string => `/api/v1/groups/${groupId}/download`

export const getLibraryExportUrl = (): string => '/api/v1/export/library'

/** The preview kept for an item Auto sorted out (only when ``has_preview``) */
export const importPreviewUrl = (item: Pick<ImportItem, 'id' | 'job_id'>): string =>
  `/api/v1/imports/${item.job_id}/items/${item.id}/preview`
