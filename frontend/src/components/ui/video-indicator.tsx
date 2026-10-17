import { Play } from 'lucide-react'

interface VideoIndicatorProps {
  /** sm: h-5 top-1 left-1 (compact tiles) · md: h-6 top-2 left-2 (default) */
  size?: 'sm' | 'md'
  /** Override default position classes (e.g. "bottom-1 left-1" instead of "top-1 left-1") */
  className?: string
}

export function VideoIndicator({ size = 'md', className }: VideoIndicatorProps) {
  if (size === 'sm') {
    return (
      <div
        className={`absolute ${className ?? 'top-1 left-1'} z-10 flex items-center justify-center h-5 w-5 rounded-full bg-black/35 hc:bg-black/75 text-white/60 hc:text-white backdrop-blur-sm`}
      >
        <Play className="h-2.5 w-2.5 fill-current" />
      </div>
    )
  }
  return (
    <div
      className={`absolute ${className ?? 'top-2 left-2'} z-10 flex items-center justify-center h-6 w-6 rounded-full bg-black/35 hc:bg-black/75 text-white/60 hc:text-white backdrop-blur-sm`}
    >
      <Play className="h-3 w-3 fill-current" />
    </div>
  )
}
