import { useState, useCallback } from 'react'
import { groupApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { SAVED_INDICATOR_DURATION_MS } from '@/lib/constants'
import { ALL_TAB } from '@/hooks/useFileEditing'
import { imageToEditable, buildPayload, toImageEdit } from '@/hooks/useEditGroupLoad'
import type { EditableGroupState, GroupPickerItem } from '@/types'

// ── Types ──────────────────────────────────────────────────────────────────

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

  // Single-group operations
  moveToNewGroup: (sourceGroupId: string) => Promise<void>
  handleDelete: () => Promise<void>
  handleMerge: (targetGroup: { id: number }) => Promise<void>

  // Mass-edit per-group operations
  handleDeleteGroup: (gId: string) => Promise<void>
  handleMergeGroup: (sourceId: string, targetGroup: GroupPickerItem) => Promise<void>
  removeGroupFromView: (gId: string) => void

  // Merge all
  confirmingMergeAll: boolean
  setConfirmingMergeAll: React.Dispatch<React.SetStateAction<boolean>>
  handleMergeAll: () => Promise<void>

  // Nav actions state (mass-edit mode)
  mergeSourceGroupId: string | null
  setMergeSourceGroupId: React.Dispatch<React.SetStateAction<string | null>>
  deleteConfirmGroupId: string | null
  setDeleteConfirmGroupId: React.Dispatch<React.SetStateAction<string | null>>
  showMergePicker: boolean
  setShowMergePicker: React.Dispatch<React.SetStateAction<boolean>>
  confirmingDelete: boolean
  setConfirmingDelete: React.Dispatch<React.SetStateAction<boolean>>

  // Bulk operations (sidebar multiselect)
  confirmingBulkMerge: boolean
  setConfirmingBulkMerge: React.Dispatch<React.SetStateAction<boolean>>
  confirmingBulkDelete: boolean
  setConfirmingBulkDelete: React.Dispatch<React.SetStateAction<boolean>>
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

// ── Hook ───────────────────────────────────────────────────────────────────

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
  // ── State ────────────────────────────────────────────────────────────────

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [showMergePicker, setShowMergePicker] = useState(false)
  const [merging, setMerging] = useState(false)
  const [groupSaving, setGroupSaving] = useState<Set<string>>(new Set())
  const [groupSaved, setGroupSaved] = useState<Set<string>>(new Set())
  const [mergeSourceGroupId, setMergeSourceGroupId] = useState<string | null>(null)
  const [deleteConfirmGroupId, setDeleteConfirmGroupId] = useState<string | null>(null)
  const [confirmingMergeAll, setConfirmingMergeAll] = useState(false)
  const [confirmingBulkMerge, setConfirmingBulkMerge] = useState(false)
  const [confirmingBulkDelete, setConfirmingBulkDelete] = useState(false)

  // ── Reset ────────────────────────────────────────────────────────────────

  const resetOperations = useCallback(() => {
    setSaving(false)
    setSaveError(null)
    setConfirmingDelete(false)
    setShowMergePicker(false)
    setMerging(false)
    setGroupSaving(new Set())
    setGroupSaved(new Set())
    setMergeSourceGroupId(null)
    setDeleteConfirmGroupId(null)
    setConfirmingMergeAll(false)
    setConfirmingBulkMerge(false)
    setConfirmingBulkDelete(false)
  }, [])

  // ── Auto-save ────────────────────────────────────────────────────────────

  const autoSaveGroup = useCallback(async (group: EditableGroupState) => {
    const gId = Number(group.id)
    if (isNaN(gId)) return // Skip locally-created groups (UUID keys — not in DB yet)

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

  // ── moveToNewGroup (API-backed split) ────────────────────────────────────

  const moveToNewGroup = async (sourceGroupId: string) => {
    const sourceIndex = groups.findIndex((g) => g.id === sourceGroupId)
    if (sourceIndex === -1) return
    const source = groups[sourceIndex]
    const sel = selections[sourceGroupId] ?? new Set<string>()
    if (sel.size === 0) return
    const sourceGId = Number(sourceGroupId)
    if (isNaN(sourceGId)) return

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
      })

      // Reload both groups from API so we have real IDs
      const newGroupId = response.new_group_ids[0]
      const fetches: Promise<Awaited<ReturnType<typeof groupApi.get>>>[] = [groupApi.get(sourceGId)]
      if (newGroupId) fetches.push(groupApi.get(newGroupId))
      const [updatedSource, newGroup] = await Promise.all(fetches)

      const toEditable = (g: typeof updatedSource): EditableGroupState => ({
        id: String(g.id),
        author: g.author ?? '',
        group_name: g.base_name,
        files: g.images.map((img) => imageToEditable(img)),
        skip: false,
        status: 'pending',
        processed: 0,
        failed: 0,
        total: g.images.length,
      })

      const newGroups = [
        ...groups.map((g, i) => (i === sourceIndex ? toEditable(updatedSource) : g)),
        ...(newGroup ? [toEditable(newGroup)] : []),
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

  // ── Delete group (single-group mode only) ────────────────────────────────

  const handleDelete = async () => {
    const gId = groupId ?? null
    if (gId === null) return
    setSaving(true)
    try {
      await groupApi.delete(gId)
      onSave()
      onClose()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Delete failed'))
      setSaving(false)
      setConfirmingDelete(false)
    }
  }

  // ── Merge into another group (single-group mode only) ────────────────────

  const handleMerge = async (targetGroup: { id: number }) => {
    const gId = groupId ?? null
    if (gId === null) return
    setMerging(true)
    try {
      await groupApi.merge(gId, targetGroup.id)
      setShowMergePicker(false)
      onSave()
      onClose()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge failed'))
      setMerging(false)
    }
  }

  // ── Per-group nav actions (mass-edit mode) ───────────────────────────────

  const handleDeleteGroup = async (gId: string) => {
    const idx = groups.findIndex((g) => g.id === gId)
    setSaving(true)
    setSaveError(null)
    try {
      await groupApi.delete(Number(gId))
      setGroups((prev) => prev.filter((g) => g.id !== gId))
      setDeleteConfirmGroupId(null)
      if (activeTab !== ALL_TAB) {
        if (idx < activeTab) setActiveTab(activeTab - 1)
        else if (idx === activeTab) setActiveTab(Math.max(0, activeTab - 1))
      }
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Delete failed'))
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
            total: reloaded.images.length,
          }
        })
      }

      setGroups(updatedGroups)
      setMergeSourceGroupId(null)
      if (activeTab !== ALL_TAB) {
        if (idx < activeTab) setActiveTab(activeTab - 1)
        else if (idx === activeTab) setActiveTab(Math.max(0, activeTab - 1))
      }
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge failed'))
    } finally {
      setMerging(false)
    }
  }

  // ── Remove group from view (mass-edit only, no delete) ───────────────────

  const removeGroupFromView = (gId: string) => {
    const idx = groups.findIndex((g) => g.id === gId)
    setGroups((prev) => prev.filter((g) => g.id !== gId))
    if (activeTab !== ALL_TAB) {
      if (idx < activeTab) setActiveTab(activeTab - 1)
      else if (idx === activeTab) setActiveTab(ALL_TAB)
    }
  }

  // ── Merge all groups (mass-edit only) ────────────────────────────────────

  const handleMergeAll = async () => {
    if (groups.length < 2) return
    const target = groups[0]
    const sources = groups.slice(1)
    setMerging(true)
    setSaveError(null)
    setConfirmingMergeAll(false)
    try {
      for (const source of sources) {
        await groupApi.merge(Number(source.id), Number(target.id))
      }
      // Reload the merged target from API
      const reloaded = await groupApi.get(Number(target.id))
      const seedIds = new Set(
        groups.flatMap((g) =>
          g.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path)),
        ),
      )
      setGroups([
        {
          id: String(reloaded.id),
          author: reloaded.author ?? '',
          group_name: reloaded.base_name,
          files: reloaded.images.map((img) => imageToEditable(img, !seedIds.has(img.id))),
          skip: false,
          status: 'pending',
          processed: 0,
          failed: 0,
          total: reloaded.images.length,
        },
      ])
      setActiveTab(0)
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge all failed'))
    } finally {
      setMerging(false)
    }
  }

  // ── Bulk operations (sidebar multiselect) ────────────────────────────────

  const handleBulkMerge = async (selectedGroupIds: Set<string>) => {
    const ids = [...selectedGroupIds]
    if (ids.length < 2) return
    const targetId = ids[0]
    const sourceIds = ids.slice(1)
    setMerging(true)
    setSaveError(null)
    setConfirmingBulkMerge(false)

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

      // Reload the target to get its current state
      const reloaded = await groupApi.get(Number(targetId))
      setGroups(
        remainingGroups.map((g) => {
          if (g.id !== targetId) return g
          return {
            ...g,
            author: reloaded.author ?? '',
            group_name: reloaded.base_name,
            files: reloaded.images.map((img) => imageToEditable(img, !seedIds.has(img.id))),
            total: reloaded.images.length,
          }
        }),
      )
      setActiveTab(ALL_TAB)
      invalidateGallery()
    } catch {
      // If even the resync fails, we can't do much — the error is already shown
    } finally {
      setMerging(false)
    }
  }

  // ── DnD-triggered API operations ───────────────────────────────────────

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
          Number(targetGroupId),
          imageIds,
        )

        // Eagerly reload target group from API so we have accurate data
        const reloaded = await groupApi.get(Number(targetGroupId))

        // Use updater form to avoid stale-closure reads of groups/activeTab
        const movedIdSet = new Set(imageIds.map(String))
        setGroups((prev) => {
          let newGroups = prev.map((g) => {
            if (g.id === drag.groupId) {
              const remaining = g.files.filter((f) => !movedIdSet.has(f.relative_path))
              return { ...g, files: remaining, total: remaining.length }
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
                total: reloaded.images.length,
              }
            }
            return g
          })

          // If source group was auto-deleted, remove it from the array
          if (result.source_group_deleted) {
            const sourceIdx = newGroups.findIndex((g) => g.id === drag.groupId)
            newGroups = newGroups.filter((g) => g.id !== drag.groupId)
            setActiveTab((prevTab) => {
              if (prevTab === ALL_TAB) return prevTab
              if (sourceIdx < prevTab) return prevTab - 1
              if (sourceIdx === prevTab) return Math.max(0, prevTab - 1)
              return prevTab
            })
          }

          return newGroups
        })

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
              total: reloaded.images.length,
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
    setConfirmingBulkDelete(false)

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
    confirmingMergeAll,
    setConfirmingMergeAll,
    handleMergeAll,
    mergeSourceGroupId,
    setMergeSourceGroupId,
    deleteConfirmGroupId,
    setDeleteConfirmGroupId,
    showMergePicker,
    setShowMergePicker,
    confirmingDelete,
    setConfirmingDelete,
    confirmingBulkMerge,
    setConfirmingBulkMerge,
    confirmingBulkDelete,
    setConfirmingBulkDelete,
    handleBulkMerge,
    handleBulkDelete,
    handleMoveImagesToGroup,
    handleDragMergeConfirm,
    resetOperations,
  }
}
