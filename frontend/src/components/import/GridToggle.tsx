interface GridToggleProps {
  gridded: boolean | null
  gridType: string | null
  onChange: (gridded: boolean | null, gridType: string | null) => void
  disabled?: boolean
  compact?: boolean
}

type GridOption = {
  label: string
  gridded: boolean | null
  gridType: string | null
}

const OPTIONS: GridOption[] = [
  { label: 'Square', gridded: true, gridType: 'square' },
  { label: 'Hex', gridded: true, gridType: 'hex' },
  { label: 'None', gridded: false, gridType: null },
  { label: '?', gridded: null, gridType: null },
]

function isActive(opt: GridOption, gridded: boolean | null, gridType: string | null): boolean {
  if (opt.gridded !== gridded) return false
  // For gridded=true options, also match grid_type
  if (opt.gridded === true) return opt.gridType === gridType
  // For None (false) and ? (null), gridded match is sufficient
  return true
}

export function GridToggle({ gridded, gridType, onChange, disabled, compact }: GridToggleProps) {
  const btnSize = compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2.5 py-1 text-[11px]'

  return (
    <div className="inline-flex rounded-md overflow-hidden border border-border">
      {OPTIONS.map((opt, i) => (
        <button
          key={opt.label}
          disabled={disabled}
          onClick={() => onChange(opt.gridded, opt.gridType)}
          className={`${btnSize} font-medium transition-all disabled:opacity-40
            ${i > 0 ? 'border-l border-border' : ''}
            ${
              isActive(opt, gridded, gridType)
                ? 'bg-primary/20 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
            }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
