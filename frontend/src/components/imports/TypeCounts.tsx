/**
 * A group's images as counts per kind, each with its icon: maps, scenes, and images
 * Auto skipped. Zero counts are left out, so a group that is all maps reads "14 ⊞" and
 * a mixed one grows a second icon: that is how a surprising Auto sort stands out. Used
 * by the import report's groups and the group editor's sidebar.
 */

import { Grid3X3, Image as ImageIcon, ImageOff, type LucideIcon } from 'lucide-react'
import { plural } from './format'

interface TypeCountsProps {
  maps: number
  scenes: number
  /** Images Auto skipped from the group (still includable) */
  skipped?: number
  className?: string
}

const KINDS: {
  key: 'maps' | 'scenes' | 'skipped'
  icon: LucideIcon
  label: (n: number) => string
}[] = [
  { key: 'maps', icon: Grid3X3, label: (n) => plural(n, 'map') },
  { key: 'scenes', icon: ImageIcon, label: (n) => plural(n, 'scene') },
  { key: 'skipped', icon: ImageOff, label: (n) => `${n.toLocaleString()} skipped by Auto` },
]

export function TypeCounts({ maps, scenes, skipped = 0, className = '' }: TypeCountsProps) {
  const values = { maps, scenes, skipped }
  const shown = KINDS.filter((k) => values[k.key] > 0)
  if (shown.length === 0) return null
  const description = shown.map((k) => k.label(values[k.key])).join(', ')
  return (
    <span
      className={`inline-flex items-center gap-2 tabular-nums ${className}`}
      title={description}
    >
      <span className="sr-only">{description}</span>
      {shown.map(({ key, icon: Icon }) => (
        <span key={key} className="inline-flex items-center gap-0.5" aria-hidden>
          {values[key].toLocaleString()}
          <Icon className="h-3 w-3 shrink-0" />
        </span>
      ))}
    </span>
  )
}
