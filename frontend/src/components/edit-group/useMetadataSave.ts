import { useRef } from 'react'
import { toast } from 'sonner'
import { groupApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import type { EditableGroupState } from '@/types'

interface UseMetadataSaveOptions {
  /** The groups the author and name fields edit right now */
  scopeGroups: EditableGroupState[]
  /** All tab or a multi-selection: the author field sets every scope group's author */
  showsMultipleGroups: boolean
  autoSaveGroup: (group: EditableGroupState) => Promise<void>
  onSaved: () => void
}

/**
 * Saves the author and group-name fields when they lose focus, and only if they changed.
 * One group saves as before (PUT /groups/{id}); an author typed for many groups is one
 * POST /groups/bulk-update rather than re-saving each group, which took ~20 s for 500.
 */
export function useMetadataSave({
  scopeGroups,
  showsMultipleGroups,
  autoSaveGroup,
  onSaved,
}: UseMetadataSaveOptions) {
  const dirty = useRef(false)

  const save = async () => {
    if (!dirty.current) return
    dirty.current = false
    if (!showsMultipleGroups) {
      scopeGroups.forEach((g) => void autoSaveGroup(g))
      return
    }
    const ids = scopeGroups.map((g) => Number(g.id)).filter((id) => !Number.isNaN(id))
    if (ids.length === 0) return
    const author = scopeGroups[0]?.author || null
    try {
      await groupApi.bulkUpdate(ids, author)
      onSaved()
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Saving the author failed'))
    }
  }

  return {
    /** Call on every edit of the author or name field */
    markDirty: () => {
      dirty.current = true
    },
    save,
  }
}
