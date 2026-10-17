interface ToggleSwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
}

export function ToggleSwitch({ checked, onChange, label }: ToggleSwitchProps) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      aria-label={label}
      aria-pressed={checked}
      className={`h-6 w-11 rounded-full transition-colors flex items-center px-1 ${
        checked ? 'bg-primary' : 'bg-secondary border border-border/50'
      }`}
    >
      <div
        className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  )
}
