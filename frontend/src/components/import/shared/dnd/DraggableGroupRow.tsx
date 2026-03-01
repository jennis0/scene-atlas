import { useDraggable } from '@dnd-kit/core'
import type { DragData } from './types'

export function DraggableGroupRow({
  groupId,
  isDndEnabled,
  children,
}: {
  groupId: string
  isDndEnabled: boolean
  children: React.ReactNode
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `group-${groupId}`,
    data: { type: 'group', id: groupId, groupId } satisfies DragData,
    disabled: !isDndEnabled,
  })

  return (
    <div ref={setNodeRef} {...listeners} {...attributes} style={{ opacity: isDragging ? 0.35 : 1 }}>
      {children}
    </div>
  )
}
