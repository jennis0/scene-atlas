import { Check } from 'lucide-react'
import { useRovingRadioGroup } from '@/hooks/useRovingRadioGroup'
import { PALETTES, type Palette } from '@/lib/palette'
import { useSettingRowDescriptionId } from './settingRowContext'

interface PalettePickerProps {
  value: Palette
  onChange: (palette: Palette) => void
}

/** One card per palette, each drawn in that palette's own tokens (the data-palette
 * attribute scopes them; see index.css) and in the current light/dark mode. A radio
 * group: one tab stop, arrow keys move and select. */
export function PalettePicker({ value, onChange }: PalettePickerProps) {
  const itemProps = useRovingRadioGroup(
    PALETTES.map((p) => p.value),
    value,
    onChange,
  )
  const descriptionId = useSettingRowDescriptionId()

  return (
    <div
      role="radiogroup"
      aria-label="Palette"
      aria-describedby={descriptionId}
      className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2"
    >
      {PALETTES.map((option, index) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            {...itemProps(index)}
            title={option.title}
            className={`group flex flex-col rounded-md border p-1 text-left transition-colors ${
              selected ? 'border-primary' : 'border-border/60 hover:border-border'
            }`}
          >
            <div
              data-palette={option.value}
              aria-hidden="true"
              className="rounded-[4px] bg-background p-2"
            >
              <div className="rounded-sm border border-border bg-card px-2 py-1.5">
                <span className="font-display text-lg leading-none text-card-foreground">Aa</span>
                <div className="mt-1.5 flex items-center gap-1">
                  <span className="h-1 w-6 rounded-full bg-muted-foreground/50" />
                  <span className="ml-auto h-2.5 w-10 rounded-full bg-primary" />
                </div>
              </div>
            </div>
            <span
              className={`flex items-start gap-1 px-1 pb-0.5 pt-1.5 text-xs leading-snug ${
                selected ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground'
              }`}
            >
              <span>{option.label}</span>
              {selected && (
                <Check
                  aria-hidden="true"
                  className="ml-auto mt-0.5 h-3 w-3 flex-shrink-0 text-primary-ink"
                />
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}
