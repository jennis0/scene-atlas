import { X } from 'lucide-react'
import { useGetTagColor } from '@/contexts/TagColorContext'

const SIZES = {
  sm: { chip: 'gap-0.5 px-1.5 text-[10px]', icon: 'h-2 w-2' },
  md: { chip: 'gap-1 px-2 text-[11px]', icon: 'h-2.5 w-2.5' },
}

interface TagChipProps {
  category: string
  value: string
  size?: keyof typeof SIZES
  /** Shows a remove button when set. */
  onRemove?: () => void
  removeDisabled?: boolean
  className?: string
}

/** A tag value in its category's colour. */
export function TagChip({
  category,
  value,
  size = 'md',
  onRemove,
  removeDisabled,
  className = '',
}: TagChipProps) {
  const colors = useGetTagColor()(category)
  const { chip, icon } = SIZES[size]
  return (
    <span
      title={category}
      className={`inline-flex items-center rounded-full border py-px ${chip} ${colors.bg} ${colors.text} ${colors.border} ${className}`}
    >
      <span className="capitalize">{value}</span>
      {onRemove && (
        <button
          onClick={onRemove}
          disabled={removeDisabled}
          className="ml-0.5 opacity-40 hover:opacity-100 transition-opacity disabled:cursor-not-allowed"
          title={`Remove ${category}: ${value}`}
        >
          <X className={icon} />
        </button>
      )}
    </span>
  )
}
