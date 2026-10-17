import type { ImageTypeFilter } from '../fileFilter'

interface TypeToggleProps {
  value: ImageTypeFilter
  onChange: (v: ImageTypeFilter) => void
}

const opts: { label: string; val: ImageTypeFilter }[] = [
  { label: 'All', val: 'all' },
  { label: 'Maps', val: 'battlemap' },
  { label: 'Scenes', val: 'scene' },
]

export function TypeToggle({ value, onChange }: TypeToggleProps) {
  return (
    <div className="inline-flex rounded border border-border overflow-hidden shrink-0">
      {opts.map((opt) => (
        <button
          key={opt.val}
          onClick={() => onChange(opt.val)}
          className={`px-1.5 py-0.5 text-2xs transition-colors ${
            value === opt.val
              ? 'bg-secondary text-foreground font-medium'
              : 'text-muted-foreground hover:text-muted-foreground hover:bg-secondary/50'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
