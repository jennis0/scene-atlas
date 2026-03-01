import { GripVertical } from 'lucide-react'
import type { ActiveDragState } from './types'

export function DragOverlayContent({ activeDrag }: { activeDrag: ActiveDragState | null }) {
  if (!activeDrag) return null

  if (activeDrag.type === 'card') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-primary/50 bg-card shadow-lg px-3 py-2 pointer-events-none max-w-[200px]">
        {activeDrag.previewUrl && (
          <img
            src={activeDrag.previewUrl}
            alt=""
            className="w-10 h-10 object-cover rounded shrink-0"
          />
        )}
        <span className="text-xs text-foreground truncate">{activeDrag.label ?? 'Image'}</span>
        {activeDrag.selectedCount > 1 && (
          <span className="ml-auto shrink-0 w-5 h-5 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
            {activeDrag.selectedCount}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-primary/50 bg-card shadow-lg px-3 py-2 pointer-events-none max-w-[180px]">
      <GripVertical className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
      <span className="text-xs text-foreground truncate">{activeDrag.label ?? 'Group'}</span>
    </div>
  )
}
