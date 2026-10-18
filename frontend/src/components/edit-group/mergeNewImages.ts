import { useCallback } from 'react'
import { groupApi } from '@/lib/api'
import { imageToEditable } from '@/hooks/useEditGroupLoad'
import type { EditableGroupState, GroupDetail } from '@/types'

/**
 * Loaded groups with the images the server has that they don't, appended. Files already
 * loaded are untouched (edits, exclusions and selection stay), and groups not in
 * `details` are returned as they are.
 */
export function withNewImages(
  groups: EditableGroupState[],
  details: GroupDetail[],
): EditableGroupState[] {
  const byId = new Map(details.map((d) => [String(d.id), d]))
  return groups.map((g) => {
    const detail = byId.get(g.id)
    if (!detail) return g
    const loaded = new Set(g.files.map((f) => f.relative_path))
    const added = detail.images
      .filter((img) => !loaded.has(String(img.id)))
      .map((img) => imageToEditable(img))
    return added.length > 0 ? { ...g, files: [...g.files, ...added] } : g
  })
}

/**
 * Bring images imported into already-loaded groups into the editor (e.g. ones included
 * from the skipped list). Not a user edit, so it doesn't save the group.
 */
export function useMergeNewImages(
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>,
) {
  return useCallback(
    async (groupIds: number[]) => {
      const details = await groupApi.details(groupIds)
      setGroups((prev) => withNewImages(prev, details))
    },
    [setGroups],
  )
}
