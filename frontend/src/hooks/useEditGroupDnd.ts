import { useState, useCallback, useRef, useMemo } from 'react'
import { PointerSensor, KeyboardSensor, useSensor, useSensors } from '@dnd-kit/core'
import type { DragStartEvent, DragEndEvent, Modifier } from '@dnd-kit/core'
import { snapCenterToCursor } from '@dnd-kit/modifiers'
import type { EditableGroupState, EditableFileState } from '@/types'
import type { DragData, DropData, ActiveDragState } from '@/components/import/shared/dnd'

interface UseEditGroupDndOptions {
  groups: EditableGroupState[]
  selections: Record<string, Set<string>>
  selectedGroupIds: Set<string>
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
  dragModifiers: Modifier[]
  dragMergeSourceIds: string[] | null
  dragMergeTarget: string | null
  setDragMergeSourceIds: React.Dispatch<React.SetStateAction<string[] | null>>
  setDragMergeTarget: React.Dispatch<React.SetStateAction<string | null>>
  handleDragStart: (event: DragStartEvent) => void
  handleDragEnd: (event: DragEndEvent) => void
  resetDnd: () => void
}

export function useEditGroupDnd({
  groups,
  selections,
  selectedGroupIds,
  updateFilesInGroup,
  handleMoveImagesToGroup,
}: UseEditGroupDndOptions): UseEditGroupDndReturn {
  const [activeDrag, setActiveDrag] = useState<ActiveDragState | null>(null)
  const [dragMergeSourceIds, setDragMergeSourceIds] = useState<string[] | null>(null)
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
        const isPartOfMultiSelect = selectedGroupIds.has(data.groupId) && selectedGroupIds.size >= 2
        setActiveDrag({
          type: 'group',
          id: data.id,
          groupId: data.groupId,
          selectedCount: isPartOfMultiSelect ? selectedGroupIds.size : 1,
          label: group?.group_name,
          selectedGroupIds: isPartOfMultiSelect ? new Set(selectedGroupIds) : undefined,
        })
      }
    },
    [selections, groups, selectedGroupIds],
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { over } = event
      if (!over || !activeDrag) {
        setActiveDrag(null)
        return
      }

      const dropData = over.data.current as DropData | undefined
      if (!dropData) {
        setActiveDrag(null)
        return
      }
      if (activeDrag.type === 'card' && dropData.type === 'group' && dropData.groupId) {
        moveToGroupRef.current(activeDrag, dropData.groupId)
      } else if (activeDrag.type === 'card' && dropData.type === 'subgroup') {
        moveToSubgroupRef.current(activeDrag, dropData.subgroup ?? null)
      } else if (activeDrag.type === 'group' && dropData.type === 'group' && dropData.groupId) {
        if (activeDrag.selectedGroupIds) {
          // Multi-group drag: merge all selected groups (except the target) into the target
          const sourceIds = [...activeDrag.selectedGroupIds].filter((id) => id !== dropData.groupId)
          if (sourceIds.length > 0) {
            setDragMergeSourceIds(sourceIds)
            setDragMergeTarget(dropData.groupId!)
          }
        } else if (activeDrag.groupId !== dropData.groupId) {
          // Single group drag
          setDragMergeSourceIds([activeDrag.groupId])
          setDragMergeTarget(dropData.groupId)
        }
      }
      setActiveDrag(null)
    },
    [activeDrag],
  )

  // Snap overlay to cursor only for multi-item drags (single drags keep natural feel)
  const conditionalSnapModifier: Modifier = useCallback(
    (args) => {
      if (activeDrag && activeDrag.selectedCount > 1) {
        return snapCenterToCursor(args)
      }
      return args.transform
    },
    [activeDrag],
  )
  const dragModifiers = useMemo(() => [conditionalSnapModifier], [conditionalSnapModifier])

  const resetDnd = useCallback(() => {
    setActiveDrag(null)
    setDragMergeSourceIds(null)
    setDragMergeTarget(null)
  }, [])

  return {
    sensors,
    activeDrag,
    dragModifiers,
    dragMergeSourceIds,
    dragMergeTarget,
    setDragMergeSourceIds,
    setDragMergeTarget,
    handleDragStart,
    handleDragEnd,
    resetDnd,
  }
}
