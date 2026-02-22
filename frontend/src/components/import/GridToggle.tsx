interface GridToggleProps {
  gridded: boolean | null
  gridType: string | null
  onChange: (gridded: boolean | null, gridType: string | null) => void
  disabled?: boolean
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

export function GridToggle({ gridded, gridType, onChange, disabled }: GridToggleProps) {
  return (
    <div className="inline-flex rounded-md overflow-hidden border border-border">
      {OPTIONS.map((opt, i) => (
        <button
          key={opt.label}
          disabled={disabled}
          onClick={() => onChange(opt.gridded, opt.gridType)}
          className={`px-2.5 py-1 text-[11px] font-medium transition-all disabled:opacity-40
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
