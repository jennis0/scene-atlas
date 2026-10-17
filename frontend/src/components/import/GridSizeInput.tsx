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

const defaultClass = `w-11 px-1.5 py-0.5 text-[11px] ${baseClass}`
const compactClass = `w-[30px] h-[18px] px-1 py-0 text-[10px] font-mono ${baseClass}`

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
    const w = parseInt(wDraft) || null
    if (w !== width) onChange(w, height)
  }

  const commitHeight = () => {
    const h = parseInt(hDraft) || null
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
        disabled={disabled}
        className={inputClass}
      />
      <span className={compact ? 'text-[10px]' : 'text-[11px]'}>&times;</span>
      <input
        type="number"
        value={hDraft}
        onChange={(e) => setHDraft(e.target.value)}
        onBlur={commitHeight}
        onKeyDown={handleKeyDown}
        placeholder="H"
        min={1}
        disabled={disabled}
        className={inputClass}
      />
    </div>
  )
}
