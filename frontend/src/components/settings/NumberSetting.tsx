import { Input } from '@/components/ui/input'

interface NumberSettingProps {
  value: string | number
  onChange: (raw: string) => void
  min: number
  max: number
  inputMode: 'numeric' | 'decimal'
  ariaLabel: string
  unit?: string
  widthClass?: string
}

export function NumberSetting({
  value,
  onChange,
  min,
  max,
  inputMode,
  ariaLabel,
  unit,
  widthClass = 'w-20',
}: NumberSettingProps) {
  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        inputSize="compact"
        min={String(min)}
        max={String(max)}
        inputMode={inputMode}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${widthClass} text-right font-mono [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none`}
        aria-label={ariaLabel}
      />
      <span className="w-8 shrink-0 text-xs text-muted-foreground">{unit}</span>
    </div>
  )
}
