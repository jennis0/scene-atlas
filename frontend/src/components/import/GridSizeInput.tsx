import { useState, useEffect } from 'react'

interface GridSizeInputProps {
  width: number | null
  height: number | null
  onChange: (width: number | null, height: number | null) => void
  disabled?: boolean
  compact?: boolean
}

const baseClass =
  'bg-secondary border border-border rounded text-foreground text-center placeholder:text-muted-foreground [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none'

const defaultClass = `w-11 px-1.5 py-0.5 text-2xs ${baseClass}`
const compactClass = `w-[30px] h-[18px] px-1 py-0 text-3xs font-mono ${baseClass}`

// The tile counts the API accepts (backend/app/models/schemas.py GridCount); anything else
// means no size
const MAX_GRID_COUNT = 10_000

function gridCount(draft: string): number | null {
  const n = parseInt(draft)
  return n >= 1 && n <= MAX_GRID_COUNT ? n : null
}

export function GridSizeInput({ width, height, onChange, disabled, compact }: GridSizeInputProps) {
  const [wDraft, setWDraft] = useState(width?.toString() ?? '')
  const [hDraft, setHDraft] = useState(height?.toString() ?? '')

  // Sync drafts when external values change (e.g. navigating between images)
  useEffect(() => {
    setWDraft(width?.toString() ?? '')
  }, [width])

  useEffect(() => {
    setHDraft(height?.toString() ?? '')
  }, [height])

  const commitWidth = () => {
    const w = gridCount(wDraft)
    if (w !== width) onChange(w, height)
  }

  const commitHeight = () => {
    const h = gridCount(hDraft)
    if (h !== height) onChange(width, h)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      e.stopPropagation()
      ;(e.target as HTMLInputElement).blur()
    }
  }

  const inputClass = compact ? compactClass : defaultClass

  return (
    <div className="flex items-center gap-1 text-xs text-muted-foreground">
      <input
        type="number"
        value={wDraft}
        onChange={(e) => setWDraft(e.target.value)}
        onBlur={commitWidth}
        onKeyDown={handleKeyDown}
        placeholder="W"
        min={1}
        max={MAX_GRID_COUNT}
        disabled={disabled}
        className={inputClass}
      />
      <span className={compact ? 'text-3xs' : 'text-2xs'}>&times;</span>
      <input
        type="number"
        value={hDraft}
        onChange={(e) => setHDraft(e.target.value)}
        onBlur={commitHeight}
        onKeyDown={handleKeyDown}
        placeholder="H"
        min={1}
        max={MAX_GRID_COUNT}
        disabled={disabled}
        className={inputClass}
      />
    </div>
  )
}
