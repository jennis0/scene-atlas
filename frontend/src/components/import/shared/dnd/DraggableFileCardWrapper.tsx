import { useDraggable } from '@dnd-kit/core'
import type { EditableFileState } from '@/types'
import type { DragData } from './types'

export function DraggableFileCardWrapper({
  file,
  groupId,
  isDndEnabled,
  children,
}: {
  file: EditableFileState
  groupId: string
  isDndEnabled: boolean
  children: React.ReactNode
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `card-${groupId}-${file.relative_path}`,
    data: { type: 'card', id: file.relative_path, groupId } satisfies DragData,
    disabled: !isDndEnabled || file.excluded || file.outOfScope,
  })

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      style={{ opacity: isDragging ? 0.35 : 1, transition: 'opacity 150ms' }}
    >
      {children}
    </div>
  )
}
