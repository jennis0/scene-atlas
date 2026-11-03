import type { ImportItem } from '@/lib/import/types'
import type { Image } from '@/types'

export const getThumbnailUrl = (image: Image): string => `/api/v1/images/${image.id}/thumbnail`

export const getThumbnailUrlById = (id: number): string => `/api/v1/images/${id}/thumbnail`

export const getImageUrl = (image: Image): string => `/api/v1/images/${image.id}/file`

export const getImageUrlById = (id: number): string => `/api/v1/images/${id}/file`

/** The original as an attachment, named in the readable layout */
export const getImageDownloadUrl = (image: Image): string =>
  `/api/v1/images/${image.id}/file?download=1`

/** Groups and images as a zip: a form POST (lib/download.ts:postForDownload) */
export const getDownloadUrl = (): string => '/api/v1/downloads'

/** A finished metadata export, waiting in the server's exports folder */
export const getMetadataExportUrl = (name: string): string =>
  `/api/v1/library/metadata-export/${encodeURIComponent(name)}`

/** The preview kept for an item Auto sorted out (only when ``has_preview``) */
export const importPreviewUrl = (item: Pick<ImportItem, 'id' | 'job_id'>): string =>
  `/api/v1/imports/${item.job_id}/items/${item.id}/preview`
