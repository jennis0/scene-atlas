import { RotateCcw } from 'lucide-react'

export function RestartBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold bg-warning/10 text-warning border border-warning/30">
      <RotateCcw className="size-2.5" />
      Restart to apply
    </span>
  )
}
