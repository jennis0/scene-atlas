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
    <div className="inline-flex rounded-lg overflow-hidden border border-slate-200">
      {OPTIONS.map((opt, i) => (
        <button
          key={opt.label}
          disabled={disabled}
          onClick={() => onChange(opt.val)}
          className={`px-2 py-0.5 text-[11px] font-medium transition-all disabled:opacity-40
            ${i > 0 ? 'border-l border-slate-200' : ''}
            ${value === opt.val
              ? 'bg-emerald-600 text-white border-emerald-600'
              : 'bg-white text-slate-500 hover:bg-slate-50'
            }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
