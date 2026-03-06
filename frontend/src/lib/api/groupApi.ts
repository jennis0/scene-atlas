import { api } from './_client'
import type {
  GroupDetail,
  GroupEditRequest,
  GroupEditResponse,
  GroupSearchResponse,
  GroupMergeResponse,
  MoveImagesResponse,
} from '@/types'

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
