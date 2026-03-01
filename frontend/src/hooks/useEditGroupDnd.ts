import { useState, useCallback, useRef } from 'react'
import { PointerSensor, KeyboardSensor, useSensor, useSensors } from '@dnd-kit/core'
import type { DragStartEvent, DragEndEvent } from '@dnd-kit/core'
import type { EditableGroupState, EditableFileState } from '@/types'
import type { DragData, DropData, ActiveDragState } from '@/components/import/shared/dnd'

interface UseEditGroupDndOptions {
  groups: EditableGroupState[]
  selections: Record<string, Set<string>>
  updateFilesInGroup: (
    groupId: string,
    paths: string[],
    updates: Partial<EditableFileState>,
  ) => void
  handleMoveImagesToGroup: (
    drag: { id: string; groupId: string },
    targetGroupId: string,
  ) => Promise<void>
}

export interface UseEditGroupDndReturn {
  sensors: ReturnType<typeof useSensors>
  activeDrag: ActiveDragState | null
  dragMergeSource: string | null
  dragMergeTarget: string | null
  setDragMergeSource: React.Dispatch<React.SetStateAction<string | null>>
  setDragMergeTarget: React.Dispatch<React.SetStateAction<string | null>>
  handleDragStart: (event: DragStartEvent) => void
  handleDragEnd: (event: DragEndEvent) => void
  resetDnd: () => void
}

export function useEditGroupDnd({
  groups,
  selections,
  updateFilesInGroup,
  handleMoveImagesToGroup,
}: UseEditGroupDndOptions): UseEditGroupDndReturn {
  const [activeDrag, setActiveDrag] = useState<ActiveDragState | null>(null)
  const [dragMergeSource, setDragMergeSource] = useState<string | null>(null)
  const [dragMergeTarget, setDragMergeTarget] = useState<string | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  )

  const handleMoveImagesToSubgroup = useCallback(
    (drag: ActiveDragState, targetSubgroup: string | null) => {
      const sel = selections[drag.groupId] ?? new Set<string>()
      const paths = sel.has(drag.id) ? [...sel] : [drag.id]
      updateFilesInGroup(drag.groupId, paths, { subgroup: targetSubgroup })
    },
    [selections, updateFilesInGroup],
  )

  // Refs to avoid stale closures in handleDragEnd
  const moveToGroupRef = useRef(handleMoveImagesToGroup)
  moveToGroupRef.current = handleMoveImagesToGroup
  const moveToSubgroupRef = useRef(handleMoveImagesToSubgroup)
  moveToSubgroupRef.current = handleMoveImagesToSubgroup

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const data = event.active.data.current as DragData
      if (data.type === 'card') {
        const sel = selections[data.groupId] ?? new Set<string>()
        const count = sel.has(data.id) ? sel.size : 1
        const file = groups
          .find((g) => g.id === data.groupId)
          ?.files.find((f) => f.relative_path === data.id)
        setActiveDrag({
          type: 'card',
          id: data.id,
          groupId: data.groupId,
          selectedCount: count,
          previewUrl: file?.previewUrl,
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
    [selections, groups],
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { over } = event
      if (!over || !activeDrag) {
        setActiveDrag(null)
        return
      }

      const dropData = over.data.current as DropData
      if (activeDrag.type === 'card' && dropData.type === 'group' && dropData.groupId) {
        moveToGroupRef.current(activeDrag, dropData.groupId)
      } else if (activeDrag.type === 'card' && dropData.type === 'subgroup') {
        moveToSubgroupRef.current(activeDrag, dropData.subgroup ?? null)
      } else if (activeDrag.type === 'group' && dropData.type === 'group' && dropData.groupId) {
        if (activeDrag.groupId !== dropData.groupId) {
          setDragMergeSource(activeDrag.groupId)
          setDragMergeTarget(dropData.groupId)
        }
      }
      setActiveDrag(null)
    },
    [activeDrag],
  )

  const resetDnd = useCallback(() => {
    setActiveDrag(null)
    setDragMergeSource(null)
    setDragMergeTarget(null)
  }, [])

  return {
    sensors,
    activeDrag,
    dragMergeSource,
    dragMergeTarget,
    setDragMergeSource,
    setDragMergeTarget,
    handleDragStart,
    handleDragEnd,
    resetDnd,
  }
}
