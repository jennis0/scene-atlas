import { useState, useCallback, useRef } from 'react'
import { PointerSensor, KeyboardSensor, useSensor, useSensors } from '@dnd-kit/core'
import type { DragStartEvent, DragEndEvent } from '@dnd-kit/core'
import type { DragData, DropData, ActiveDragState } from '@/components/import/shared/dnd'
import type { UseImportStateReturn } from './useImportState'
import { importPreviewUrl } from '@/lib/importStorage'
import { resolveApiUrl } from '@/lib/apiBase'

export function useImportDnd(s: UseImportStateReturn) {
  const [activeDrag, setActiveDrag] = useState<ActiveDragState | null>(null)
  const { groups } = s.files
  const { activeSelection } = s.editing

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  )

  // Use refs for stable closures in handleDragEnd
  const moveFilesRef = useRef(s.editing.moveFilesToGroup)
  moveFilesRef.current = s.editing.moveFilesToGroup
  const mergeGroupsRef = useRef(s.editing.mergeGroups)
  mergeGroupsRef.current = s.editing.mergeGroups
  const updateFilesRef = useRef(s.editing.updateFilesInGroup)
  updateFilesRef.current = s.editing.updateFilesInGroup

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const data = event.active.data.current as DragData
      if (data.type === 'card') {
        const sel = activeSelection
        const count = sel.has(data.id) ? sel.size : 1
        const file = groups.flatMap((g) => g.files).find((f) => f.relative_path === data.id)
        const jobId = s.workflow.jobId
        setActiveDrag({
          type: 'card',
          id: data.id,
          groupId: data.groupId,
          selectedCount: count,
          previewUrl:
            file?.previewUrl ??
            (jobId
              ? resolveApiUrl(importPreviewUrl(jobId, file?.relative_path ?? data.id))
              : undefined),
          label: file?.name || file?.filename,
        })
      } else {
        const group = groups.find((g) => g.id === data.groupId)
        setActiveDrag({
          type: 'group',
          id: data.id,
          groupId: data.groupId,
          selectedCount: 1,
          label: group?.group_name,
        })
      }
    },
    [activeSelection, groups, s.workflow.jobId],
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { over } = event
      if (!over || !activeDrag) {
        setActiveDrag(null)
        return
      }

      const dropData = over.data.current as DropData
      const sel = activeSelection
      const paths = sel.has(activeDrag.id) ? [...sel] : [activeDrag.id]

      if (activeDrag.type === 'card' && dropData.type === 'group' && dropData.groupId) {
        // Card -> Group: move files to target group
        if (activeDrag.groupId !== dropData.groupId) {
          moveFilesRef.current(activeDrag.groupId, dropData.groupId, paths)
        }
      } else if (activeDrag.type === 'card' && dropData.type === 'subgroup') {
        // Card -> Subgroup: batch-update file subgroups
        updateFilesRef.current(activeDrag.groupId, paths, { subgroup: dropData.subgroup ?? null })
      } else if (activeDrag.type === 'group' && dropData.type === 'group' && dropData.groupId) {
        // Group -> Group: merge groups
        if (activeDrag.groupId !== dropData.groupId) {
          const sourceIndex = groups.findIndex((g) => g.id === activeDrag.groupId)
          const targetIndex = groups.findIndex((g) => g.id === dropData.groupId)
          if (sourceIndex !== -1 && targetIndex !== -1) {
            mergeGroupsRef.current(sourceIndex, targetIndex)
          }
        }
      }
      setActiveDrag(null)
    },
    [activeDrag, activeSelection, groups],
  )

  return { activeDrag, sensors, handleDragStart, handleDragEnd }
}
