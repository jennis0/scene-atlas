import { resolveApiUrl } from '../apiBase'
import type { Image } from '@/types'

export const getThumbnailUrl = (image: Image): string =>
  resolveApiUrl(`/api/v1/images/${image.id}/thumbnail`)

export const getThumbnailUrlById = (id: number): string =>
  resolveApiUrl(`/api/v1/images/${id}/thumbnail`)

export const getImageUrl = (image: Image): string =>
  resolveApiUrl(`/api/v1/images/${image.id}/file`)

export const getImageUrlById = (id: number): string => resolveApiUrl(`/api/v1/images/${id}/file`)

export const getGroupDownloadUrl = (groupId: number): string =>
  resolveApiUrl(`/api/v1/groups/${groupId}/download`)

export const getLibraryExportUrl = (): string => resolveApiUrl('/api/v1/export/library')
