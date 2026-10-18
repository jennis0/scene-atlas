import { useId, type ReactNode } from 'react'

interface ChoiceCardProps {
  /** Radio group name: one per set of cards */
  name: string
  value: string
  label: string
  /** Read out with the radio as its description */
  description: ReactNode
  checked: boolean
  onSelect: () => void
  /** Short visual tag in the corner, e.g. "Recommended"; also read at the end of the description */
  badge?: string
  /** Below the description, outside the radio's label (e.g. a details disclosure) */
  footer?: ReactNode
}

/** A radio card: the visually hidden radio carries the name and selection for keyboards and
 * screen readers (one tab stop per group, arrow keys move); the whole card is a mouse
 * target. Wrap a set in a `role="radiogroup"` with a label. */
export function ChoiceCard({
  name,
  value,
  label,
  description,
  checked,
  onSelect,
  badge,
  footer,
}: ChoiceCardProps) {
  const descriptionId = useId()
  return (
    <div
      onClick={onSelect}
      className={`focus-ring-within-input relative flex flex-col justify-start text-left rounded-lg border p-4 space-y-2.5 cursor-pointer transition-colors ${
        checked
          ? 'border-primary bg-primary/5'
          : 'border-border bg-card hover:border-border/80 hover:bg-accent/30'
      }`}
    >
      <label className="block font-semibold text-sm cursor-pointer">
        <input
          type="radio"
          name={name}
          value={value}
          checked={checked}
          onChange={onSelect}
          aria-describedby={descriptionId}
          className="sr-only"
        />
        {label}
      </label>

      <div id={descriptionId} className="space-y-2.5 text-xs text-muted-foreground leading-relaxed">
        {description}
        {/* Last: an sr-only first child would still push the next one down (space-y) */}
        {badge && <p className="sr-only">{badge}.</p>}
      </div>

      {footer}

      {/* Last, so the spacing between children doesn't count it */}
      {badge && (
        <span
          aria-hidden="true"
          className="absolute top-3 right-3 text-2xs font-semibold px-1.5 py-0.5 rounded bg-primary/10 text-primary"
        >
          {badge}
        </span>
      )}
    </div>
  )
}
