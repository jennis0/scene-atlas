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
  const { isOver, setNodeRef } = useDroppable({
    id: `group-drop-${groupId}`,
    data: { type: 'group', groupId } satisfies DropData,
    disabled: !activeDrag || activeDrag.groupId === groupId,
  })

  // Only highlight when a compatible drag is over (card→group or group→group, not self)
  const showHighlight = isOver && activeDrag && activeDrag.groupId !== groupId

  return (
    <div
      ref={setNodeRef}
      className={`transition-colors ${showHighlight ? 'ring-1 ring-inset ring-primary/50 bg-primary/5' : ''}`}
    >
      {children}
    </div>
  )
}
