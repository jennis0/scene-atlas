import { useState, useCallback, useRef } from 'react'
import { groupApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { serverId } from '@/lib/serverId'
import { SAVED_INDICATOR_DURATION_MS } from '@/lib/constants'
import { ALL_TAB } from '@/hooks/useFileEditing'
import {
  imageToEditable,
  buildPayload,
  deletedImageIds,
  toImageEdit,
  groupDetailToEditable,
  tabAfterRemoval,
} from '@/hooks/useEditGroupLoad'
import type { EditableGroupState, GroupPickerItem } from '@/types'

export interface UseEditGroupOperationsOptions {
  /** Group ID for single-group mode */
  groupId?: number | null
  groups: EditableGroupState[]
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>
  activeTab: number
  setActiveTab: React.Dispatch<React.SetStateAction<number>>
  selections: Record<string, Set<string>>
  deselectAll: (groupId: string) => void
  invalidateGallery: () => void
  onSave: () => void
  onClose: () => void
}

export interface UseEditGroupOperationsReturn {
  // Status
  saving: boolean
  saveError: string | null
  merging: boolean
  groupSaving: Set<string>
  groupSaved: Set<string>

  // Auto-save
  autoSaveGroup: (group: EditableGroupState) => Promise<void>

  // The operations that resolve to a boolean report success, so callers can keep a
  // confirmation open on failure.

  // Single-group operations
  moveToNewGroup: (sourceGroupId: string) => Promise<void>
  handleDelete: () => Promise<boolean>
  handleMerge: (targetGroup: { id: number }) => Promise<boolean>

  // Mass-edit per-group operations
  handleDeleteGroup: (gId: string) => Promise<boolean>
  handleMergeGroup: (sourceId: string, targetGroup: GroupPickerItem) => Promise<boolean>
  removeGroupFromView: (gId: string) => void
  handleMergeAll: () => Promise<void>

  // Bulk operations (sidebar multiselect)
  handleBulkMerge: (selectedGroupIds: Set<string>) => Promise<void>
  handleBulkDelete: (selectedGroupIds: Set<string>) => Promise<void>

  // DnD-triggered API operations
  handleMoveImagesToGroup: (
    drag: { id: string; groupId: string },
    targetGroupId: string,
  ) => Promise<void>
  handleDragMergeConfirm: (dragMergeSourceIds: string[], dragMergeTarget: string) => Promise<void>

  // Reset
  resetOperations: () => void
}

export function useEditGroupOperations({
  groupId,
  groups,
  setGroups,
  activeTab,
  setActiveTab,
  selections,
  deselectAll,
  invalidateGallery,
  onSave,
  onClose,
}: UseEditGroupOperationsOptions): UseEditGroupOperationsReturn {
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [merging, setMerging] = useState(false)
  const [groupSaving, setGroupSaving] = useState<Set<string>>(new Set())
  const [groupSaved, setGroupSaved] = useState<Set<string>>(new Set())

  // handleMoveImagesToGroup reads groups after an await; the ref gives it the latest.
  const groupsRef = useRef(groups)
  groupsRef.current = groups

  const resetOperations = useCallback(() => {
    setSaving(false)
    setSaveError(null)
    setMerging(false)
    setGroupSaving(new Set())
    setGroupSaved(new Set())
  }, [])

  const autoSaveGroup = useCallback(async (group: EditableGroupState) => {
    const gId = serverId(group.id)
    if (gId === null) return // Skip locally-created groups (not in the DB yet)

    setGroupSaving((prev) => {
      const s = new Set(prev)
      s.add(group.id)
      return s
    })
    setSaveError(null)
    try {
      await groupApi.edit(gId, buildPayload(group))
      setGroupSaved((prev) => {
        const s = new Set(prev)
        s.add(group.id)
        return s
      })
      setTimeout(() => {
        setGroupSaved((prev) => {
          const s = new Set(prev)
          s.delete(group.id)
          return s
        })
      }, SAVED_INDICATOR_DURATION_MS)
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Auto-save failed'))
    } finally {
      setGroupSaving((prev) => {
        const s = new Set(prev)
        s.delete(group.id)
        return s
      })
    }
  }, [])

  const moveToNewGroup = async (sourceGroupId: string) => {
    const sourceIndex = groups.findIndex((g) => g.id === sourceGroupId)
    if (sourceIndex === -1) return
    const source = groups[sourceIndex]
    const sel = selections[sourceGroupId] ?? new Set<string>()
    if (sel.size === 0) return
    const sourceGId = serverId(sourceGroupId)
    if (sourceGId === null) return

    const movedFiles = source.files.filter((f) => sel.has(f.relative_path))
    const remainingFiles = source.files.filter((f) => !sel.has(f.relative_path))

    setSaving(true)
    setSaveError(null)
    try {
      const response = await groupApi.edit(sourceGId, {
        base_name: source.group_name,
        author: source.author || undefined,
        images: remainingFiles.filter((f) => !f.excluded).map(toImageEdit),
        new_groups: [
          {
            base_name: `${source.group_name} (split)`,
            author: source.author || undefined,
            image_ids: movedFiles.filter((f) => !f.excluded).map((f) => Number(f.relative_path)),
          },
        ],
        delete_image_ids: deletedImageIds(source.files),
      })

      // Reload both groups from the API so the new one has its real ID.
      const newGroupId = response.new_group_ids[0]
      const fetches = [groupApi.get(sourceGId)]
      if (newGroupId) fetches.push(groupApi.get(newGroupId))
      const [updatedSource, newGroup] = await Promise.all(fetches)

      const newGroups = [
        ...groups.map((g, i) => (i === sourceIndex ? groupDetailToEditable(updatedSource) : g)),
        ...(newGroup ? [groupDetailToEditable(newGroup)] : []),
      ]
      setGroups(newGroups)
      setActiveTab(newGroups.length - 1)
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Split failed'))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    const gId = groupId ?? null
    if (gId === null) return false
    setSaving(true)
    try {
      await groupApi.delete(gId)
      onSave()
      onClose()
      return true
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Delete failed'))
      setSaving(false)
      return false
    }
  }

  const handleMerge = async (targetGroup: { id: number }) => {
    const gId = groupId ?? null
    if (gId === null) return false
    setMerging(true)
    try {
      await groupApi.merge(gId, targetGroup.id)
      onSave()
      onClose()
      return true
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge failed'))
      setMerging(false)
      return false
    }
  }

  const handleDeleteGroup = async (gId: string) => {
    const idx = groups.findIndex((g) => g.id === gId)
    setSaving(true)
    setSaveError(null)
    try {
      await groupApi.delete(Number(gId))
      setGroups((prev) => prev.filter((g) => g.id !== gId))
      setActiveTab(tabAfterRemoval(activeTab, idx, Math.max(0, activeTab - 1)))
      invalidateGallery()
      return true
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Delete failed'))
      return false
    } finally {
      setSaving(false)
    }
  }

  const handleMergeGroup = async (sourceId: string, targetGroup: GroupPickerItem) => {
    const idx = groups.findIndex((g) => g.id === sourceId)
    setMerging(true)
    setSaveError(null)
    try {
      await groupApi.merge(Number(sourceId), targetGroup.id)

      // If target group is also open in this dialog, reload it from the API
      const targetInGroups = groups.some((g) => g.id === String(targetGroup.id))
      let updatedGroups = groups.filter((g) => g.id !== sourceId)

      if (targetInGroups) {
        const reloaded = await groupApi.get(targetGroup.id)
        // Preserve outOfScope flags for the target group's existing images
        const originalTarget = groups.find((g) => g.id === String(targetGroup.id))
        const originalSeedIds = new Set(
          originalTarget?.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path)) ??
            [],
        )
        updatedGroups = updatedGroups.map((g) => {
          if (g.id !== String(targetGroup.id)) return g
          return {
            ...g,
            files: reloaded.images.map((img) => imageToEditable(img, !originalSeedIds.has(img.id))),
          }
        })
      }

      setGroups(updatedGroups)
      setActiveTab(tabAfterRemoval(activeTab, idx, Math.max(0, activeTab - 1)))
      invalidateGallery()
      return true
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge failed'))
      return false
    } finally {
      setMerging(false)
    }
  }

  const removeGroupFromView = (gId: string) => {
    const idx = groups.findIndex((g) => g.id === gId)
    setGroups((prev) => prev.filter((g) => g.id !== gId))
    setActiveTab(tabAfterRemoval(activeTab, idx, ALL_TAB))
  }

  const handleBulkMerge = async (selectedGroupIds: Set<string>) => {
    const ids = [...selectedGroupIds]
    if (ids.length < 2) return
    const targetId = ids[0]
    const sourceIds = ids.slice(1)
    setMerging(true)
    setSaveError(null)

    const mergedSourceIds: string[] = []
    try {
      for (const sourceId of sourceIds) {
        await groupApi.merge(Number(sourceId), Number(targetId))
        mergedSourceIds.push(sourceId)
      }
    } catch (err) {
      setSaveError(
        getApiErrorMessage(
          err,
          `Bulk merge failed after merging ${mergedSourceIds.length}/${sourceIds.length} groups`,
        ),
      )
    }

    // Resync local state from the API regardless of partial failure
    try {
      const seedIds = new Set(
        groups
          .filter((g) => selectedGroupIds.has(g.id))
          .flatMap((g) => g.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path))),
      )
      const deletedSet = new Set(mergedSourceIds)
      const remainingGroups = groups.filter((g) => !deletedSet.has(g.id))

      const reloaded = await groupApi.get(Number(targetId))
      setGroups(
        remainingGroups.map((g) => {
          if (g.id !== targetId) return g
          return {
            ...g,
            author: reloaded.author ?? '',
            group_name: reloaded.base_name,
            files: reloaded.images.map((img) => imageToEditable(img, !seedIds.has(img.id))),
          }
        }),
      )
      setActiveTab(remainingGroups.length === 1 ? 0 : ALL_TAB)
      invalidateGallery()
    } catch {
      // The resync failed too; the merge error is already shown.
    } finally {
      setMerging(false)
    }
  }

  /** Merges every group into the first. */
  const handleMergeAll = async () => {
    await handleBulkMerge(new Set(groups.map((g) => g.id)))
  }

  const handleMoveImagesToGroup = useCallback(
    async (drag: { id: string; groupId: string }, targetGroupId: string) => {
      if (drag.groupId === targetGroupId) return

      const sel = selections[drag.groupId] ?? new Set<string>()
      const imageIds = sel.has(drag.id) ? [...sel].map(Number) : [Number(drag.id)]

      setSaving(true)
      setSaveError(null)
      try {
        const result = await groupApi.moveImages(
          Number(drag.groupId),
          { groupId: Number(targetGroupId) },
          imageIds,
        )

        const reloaded = await groupApi.get(Number(targetGroupId))

        // Use updater form to avoid stale-closure reads of groups/activeTab
        const movedIdSet = new Set(imageIds.map(String))
        setGroups((prev) => {
          const newGroups = prev.map((g) => {
            if (g.id === drag.groupId) {
              return { ...g, files: g.files.filter((f) => !movedIdSet.has(f.relative_path)) }
            }
            if (g.id === targetGroupId) {
              // Preserve outOfScope flags for images that were already in scope
              const originalSeedIds = new Set(
                g.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path)),
              )
              imageIds.forEach((id) => originalSeedIds.add(id))
              return {
                ...g,
                files: reloaded.images.map((img) =>
                  imageToEditable(img, !originalSeedIds.has(img.id)),
                ),
              }
            }
            return g
          })
          // The server deletes a source group that the move emptied.
          return result.source_group_deleted
            ? newGroups.filter((g) => g.id !== drag.groupId)
            : newGroups
        })
        if (result.source_group_deleted) {
          // Updaters must be pure, so the tab is adjusted here, from the latest rendered groups.
          const sourceIdx = groupsRef.current.findIndex((g) => g.id === drag.groupId)
          setActiveTab((prevTab) => tabAfterRemoval(prevTab, sourceIdx, Math.max(0, prevTab - 1)))
        }

        deselectAll(drag.groupId)
        invalidateGallery()
      } catch (err) {
        setSaveError(getApiErrorMessage(err, 'Move failed'))
      } finally {
        setSaving(false)
      }
    },
    [selections, setGroups, deselectAll, invalidateGallery, setActiveTab],
  )

  const handleDragMergeConfirm = async (dragMergeSourceIds: string[], dragMergeTarget: string) => {
    if (dragMergeSourceIds.length === 0 || !dragMergeTarget) return
    setMerging(true)
    setSaveError(null)

    const sourceIdSet = new Set(dragMergeSourceIds)
    const mergedSourceIds: string[] = []
    try {
      for (const sourceId of dragMergeSourceIds) {
        await groupApi.merge(Number(sourceId), Number(dragMergeTarget))
        mergedSourceIds.push(sourceId)
      }
    } catch (err) {
      setSaveError(
        getApiErrorMessage(
          err,
          mergedSourceIds.length > 0
            ? `Merge failed after merging ${mergedSourceIds.length}/${dragMergeSourceIds.length} groups`
            : 'Merge failed',
        ),
      )
    }

    // Resync local state from the API regardless of partial failure
    if (mergedSourceIds.length > 0) {
      try {
        const deletedSet = new Set(mergedSourceIds)
        const targetInGroups = groups.some((g) => g.id === dragMergeTarget)
        let updatedGroups = groups.filter((g) => !deletedSet.has(g.id))

        if (targetInGroups) {
          const reloaded = await groupApi.get(Number(dragMergeTarget))
          const originalSeedIds = new Set(
            groups
              .filter((g) => g.id === dragMergeTarget || sourceIdSet.has(g.id))
              .flatMap((g) =>
                g.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path)),
              ),
          )
          updatedGroups = updatedGroups.map((g) => {
            if (g.id !== dragMergeTarget) return g
            return {
              ...g,
              files: reloaded.images.map((img) =>
                imageToEditable(img, !originalSeedIds.has(img.id)),
              ),
            }
          })
        }

        setGroups(updatedGroups)
        setActiveTab(ALL_TAB)
        invalidateGallery()
      } catch {
        // Resync failed — error already shown above
      }
    }
    setMerging(false)
  }

  const handleBulkDelete = async (selectedGroupIds: Set<string>) => {
    const ids = [...selectedGroupIds]
    setSaving(true)
    setSaveError(null)

    const deletedIds: string[] = []
    try {
      for (const id of ids) {
        await groupApi.delete(Number(id))
        deletedIds.push(id)
      }
    } catch (err) {
      setSaveError(
        getApiErrorMessage(
          err,
          `Bulk delete failed after deleting ${deletedIds.length}/${ids.length} groups`,
        ),
      )
    }

    // Resync: remove successfully deleted groups from local state
    if (deletedIds.length > 0) {
      const deletedSet = new Set(deletedIds)
      setGroups((prev) => prev.filter((g) => !deletedSet.has(g.id)))
      if (deletedIds.length === ids.length) setActiveTab(ALL_TAB)
      invalidateGallery()
    }
    setSaving(false)
  }

  return {
    saving,
    saveError,
    merging,
    groupSaving,
    groupSaved,
    autoSaveGroup,
    moveToNewGroup,
    handleDelete,
    handleMerge,
    handleDeleteGroup,
    handleMergeGroup,
    removeGroupFromView,
    handleMergeAll,
    handleBulkMerge,
    handleBulkDelete,
    handleMoveImagesToGroup,
    handleDragMergeConfirm,
    resetOperations,
  }
}
