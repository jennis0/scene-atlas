import { RotateCcw } from 'lucide-react'

export function RestartBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-amber-500/10 text-amber-500 border border-amber-500/20">
      <RotateCcw className="size-2.5" />
      Restart to apply
    </span>
  )
}
