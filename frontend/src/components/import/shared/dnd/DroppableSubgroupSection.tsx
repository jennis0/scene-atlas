import { useDroppable } from '@dnd-kit/core'
import type { ActiveDragState, DropData } from './types'

export function DroppableSubgroupSection({
  subVariant,
  activeDrag,
  children,
}: {
  subVariant: string | null
  activeDrag: ActiveDragState | null
  children: React.ReactNode
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `subgroup-${subVariant ?? '__main__'}`,
    data: { type: 'subgroup', subgroup: subVariant } satisfies DropData,
    disabled: !activeDrag || activeDrag.type !== 'card',
  })

  const showHighlight = isOver && activeDrag?.type === 'card'

  return (
    <div
      ref={setNodeRef}
      className={`mb-2 transition-colors rounded ${showHighlight ? 'ring-1 ring-inset ring-primary/40 bg-primary/5' : ''}`}
    >
      {children}
    </div>
  )
}
