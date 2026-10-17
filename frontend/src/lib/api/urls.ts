import type { Image } from '@/types'

export const getThumbnailUrl = (image: Image): string => `/api/v1/images/${image.id}/thumbnail`

export const getThumbnailUrlById = (id: number): string => `/api/v1/images/${id}/thumbnail`

export const getImageUrl = (image: Image): string => `/api/v1/images/${image.id}/file`

export const getImageUrlById = (id: number): string => `/api/v1/images/${id}/file`

export const getGroupDownloadUrl = (groupId: number): string => `/api/v1/groups/${groupId}/download`

export const getLibraryExportUrl = (): string => '/api/v1/export/library'
