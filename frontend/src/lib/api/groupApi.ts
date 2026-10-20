import { api } from './_client'
import type {
  GroupDetail,
  GroupEditRequest,
  GroupEditResponse,
  GroupPickerResponse,
  GroupMergeResponse,
  MoveImagesResponse,
  MoveTarget,
  GroupSummary,
} from '@/types'

/** Server caps on the batch reads (backend MAX_GROUP_SUMMARY_IDS / MAX_GROUP_DETAIL_IDS) */
const MAX_SUMMARY_IDS = 5000
const MAX_DETAIL_IDS = 100

/** Call `fetch` for each chunk of `ids` one after another (the backend serialises reads). */
async function inChunks<T>(ids: number[], size: number, fetch: (chunk: number[]) => Promise<T[]>) {
  const out: T[] = []
  for (let i = 0; i < ids.length; i += size) out.push(...(await fetch(ids.slice(i, i + size))))
  return out
}

export const groupApi = {
  get: async (id: number): Promise<GroupDetail> => {
    const { data } = await api.get<GroupDetail>(`/groups/${id}`)
    return data
  },

  /** Names, counts and image ids for many groups, in the order asked. Missing groups are left out. */
  summaries: (ids: number[]): Promise<GroupSummary[]> =>
    inChunks(ids, MAX_SUMMARY_IDS, async (chunk) => {
      const { data } = await api.post<GroupSummary[]>('/groups/summaries', { ids: chunk })
      return data
    }),

  /** Full details for several groups, in the order asked. Missing groups are left out. */
  details: (ids: number[]): Promise<GroupDetail[]> =>
    inChunks(ids, MAX_DETAIL_IDS, async (chunk) => {
      const { data } = await api.post<GroupDetail[]>('/groups/details', { ids: chunk })
      return data
    }),

  /** Set many groups' author (and their images') in one request. */
  bulkUpdate: async (ids: number[], author: string | null): Promise<void> => {
    await api.post('/groups/bulk-update', { ids, author })
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
  ): Promise<GroupPickerResponse> => {
    const { data } = await api.get<GroupPickerResponse>('/groups/search', {
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

  /** Moves images out of a group into another one, or into a new group of their own. */
  moveImages: async (
    sourceGroupId: number,
    target: MoveTarget,
    imageIds: number[],
  ): Promise<MoveImagesResponse> => {
    const { data } = await api.post<MoveImagesResponse>(`/groups/${sourceGroupId}/move-images`, {
      ...('groupId' in target
        ? { target_group_id: target.groupId }
        : { new_group_name: target.newGroupName }),
      image_ids: imageIds,
    })
    return data
  },
}
