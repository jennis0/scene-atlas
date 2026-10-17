interface GridToggleProps {
  gridded: boolean | null
  gridType: string | null
  onChange: (gridded: boolean | null, gridType: string | null) => void
  disabled?: boolean
  compact?: boolean
}

type GridOption = {
  label: string
  /** Spoken name and tooltip, when the visible label is a symbol */
  title?: string
  gridded: boolean | null
  gridType: string | null
}

const OPTIONS: GridOption[] = [
  { label: 'Square', gridded: true, gridType: 'square' },
  { label: 'Hex', gridded: true, gridType: 'hex' },
  { label: 'None', gridded: false, gridType: null },
  { label: '?', title: 'Unknown', gridded: null, gridType: null },
]

function isActive(opt: GridOption, gridded: boolean | null, gridType: string | null): boolean {
  if (opt.gridded !== gridded) return false
  // For gridded=true options, also match grid_type
  if (opt.gridded === true) return opt.gridType === gridType
  // For None (false) and ? (null), gridded match is sufficient
  return true
}

export function GridToggle({ gridded, gridType, onChange, disabled, compact }: GridToggleProps) {
  const btnSize = compact ? 'px-1.5 py-0.5 text-3xs' : 'px-2.5 py-1 text-2xs'

  return (
    <div
      role="group"
      aria-label="Grid"
      className="inline-flex rounded-md overflow-hidden border border-border"
    >
      {OPTIONS.map((opt, i) => (
        <button
          key={opt.label}
          disabled={disabled}
          aria-pressed={isActive(opt, gridded, gridType)}
          aria-label={opt.title}
          title={opt.title}
          onClick={() => onChange(opt.gridded, opt.gridType)}
          className={`${btnSize} font-medium transition-all disabled:opacity-40 focus-visible:outline-offset-[-2px]
            ${i > 0 ? 'border-l border-border' : ''}
            ${
              isActive(opt, gridded, gridType)
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
            }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
