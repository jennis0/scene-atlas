import { useDroppable } from '@dnd-kit/core'
import type { ActiveDragState, DropData } from './types'

export function DroppableGroupRow({
  groupId,
  activeDrag,
  children,
}: {
  groupId: string
  activeDrag: ActiveDragState | null
  children: React.ReactNode
}) {
  const isCoSelected = activeDrag?.selectedGroupIds?.has(groupId) ?? false
  const { isOver, setNodeRef } = useDroppable({
    id: `group-drop-${groupId}`,
    data: { type: 'group', groupId } satisfies DropData,
    disabled: !activeDrag || isCoSelected,
  })

  // Only highlight when a compatible drag is over (not self, not co-selected in multi-drag)
  const showHighlight = isOver && activeDrag && activeDrag.groupId !== groupId && !isCoSelected

  return (
    <div
      ref={setNodeRef}
      className={`transition-colors ${showHighlight ? 'ring-1 ring-inset ring-primary/50 bg-primary/5' : ''}`}
    >
      {children}
    </div>
  )
}
