import { useRovingRadioGroup } from '@/hooks/useRovingRadioGroup'
import { useSettingRowDescriptionId } from './settingRowContext'

interface SegmentedControlProps<T extends string | number> {
  options: readonly { value: T; label: string; title: string }[]
  value: T
  onChange: (value: T) => void
  label: string
}

/** A radio group drawn as joined buttons: one tab stop, arrow keys move the selection.
 * Wraps rather than overflowing a narrow container (large text, small windows). */
export function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: SegmentedControlProps<T>) {
  const itemProps = useRovingRadioGroup(
    options.map((o) => o.value),
    value,
    onChange,
  )
  const descriptionId = useSettingRowDescriptionId()
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-describedby={descriptionId}
      className="flex flex-wrap max-w-full rounded-md border border-border/50 overflow-hidden"
    >
      {options.map((option, index) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            {...itemProps(index)}
            title={option.title}
            className={`px-2.5 h-7 text-xs transition-colors focus-visible:outline-offset-[-2px] ${
              selected
                ? // Windows High Contrast drops the fill; the system highlight shows the choice
                  'bg-primary text-primary-foreground forced-colors:forced-color-adjust-none forced-colors:bg-[Highlight] forced-colors:text-[HighlightText]'
                : 'bg-secondary text-muted-foreground hover:text-foreground'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
