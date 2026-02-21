interface GridToggleProps {
  value: boolean | null
  onChange: (v: boolean | null) => void
  disabled?: boolean
}

const OPTIONS: { label: string; val: boolean | null }[] = [
  { label: 'Grid', val: true },
  { label: 'Gridless', val: false },
  { label: '?', val: null },
]

export function GridToggle({ value, onChange, disabled }: GridToggleProps) {
  return (
    <div className="inline-flex rounded-md overflow-hidden border border-border">
      {OPTIONS.map((opt, i) => (
        <button
          key={opt.label}
          disabled={disabled}
          onClick={() => onChange(opt.val)}
          className={`px-2.5 py-1 text-[11px] font-medium transition-all disabled:opacity-40
            ${i > 0 ? 'border-l border-border' : ''}
            ${value === opt.val
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
