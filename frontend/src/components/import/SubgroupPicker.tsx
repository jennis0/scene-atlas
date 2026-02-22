import { useState, useEffect, useRef } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface SubgroupPickerProps {
  existingSubgroups: string[]
  onSelect: (value: string) => void
}

export function SubgroupPicker({ existingSubgroups, onSelect }: SubgroupPickerProps) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const handleEscape = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  const apply = (value: string) => {
    onSelect(value)
    setInput('')
    setOpen(false)
  }

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-primary transition-colors"
      >
        <Plus className="h-3 w-3" />
        Subgroup
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 w-52 rounded-lg border border-border bg-card shadow-2xl shadow-black/40 overflow-hidden">
          {existingSubgroups.length > 0 && (
            <div className="py-1">
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">
                Existing
              </div>
              {existingSubgroups.map((sv) => (
                <button
                  key={sv}
                  onClick={() => apply(sv)}
                  className="flex w-full items-center px-3 py-1.5 text-sm text-foreground hover:bg-primary/10 hover:text-primary transition-colors capitalize text-left"
                >
                  {sv}
                </button>
              ))}
              <div className="h-px bg-border mx-2 mt-1" />
            </div>
          )}
          <div className="p-2">
            <div className="flex gap-1.5">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="New…"
                autoFocus={existingSubgroups.length === 0}
                className="flex-1 min-w-0 h-7 px-2 text-sm bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && input.trim()) apply(input.trim())
                }}
              />
              <Button
                size="sm"
                className="h-7 text-xs flex-shrink-0"
                onClick={() => { if (input.trim()) apply(input.trim()) }}
              >
                Set
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
