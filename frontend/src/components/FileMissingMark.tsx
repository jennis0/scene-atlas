import { FileX } from 'lucide-react'

/**
 * On a tile whose original file is gone from the linked folder (design/library-setup.md
 * §4.7). Words, not only an icon, and an outline in forced colours, where the fill is
 * dropped. Hidden from screen readers: the tile's name says it instead.
 */
export function FileMissingMark({ className = 'top-2 right-2' }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`absolute ${className} z-10 inline-flex items-center gap-1 rounded bg-black/70 hc:bg-black/85 px-1.5 py-0.5 text-2xs font-medium text-white forced-colors:border`}
    >
      <FileX className="h-3 w-3 shrink-0" />
      File missing
    </span>
  )
}
