import { useState, useEffect, useRef } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface SubVariantPickerProps {
  existingSubVariants: string[]
  onSelect: (value: string) => void
}

export function SubVariantPicker({ existingSubVariants, onSelect }: SubVariantPickerProps) {
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
        className="inline-flex items-center gap-0.5 text-[11px] text-slate-300 hover:text-emerald-500 transition-colors"
      >
        <Plus className="h-3 w-3" />
        Sub-variant
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 w-52 rounded-lg border bg-white shadow-xl shadow-black/5 overflow-hidden">
          {existingSubVariants.length > 0 && (
            <div className="py-1">
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold text-slate-400 uppercase tracking-widest">
                Existing
              </div>
              {existingSubVariants.map((sv) => (
                <button
                  key={sv}
                  onClick={() => apply(sv)}
                  className="flex w-full items-center px-3 py-1.5 text-sm text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 transition-colors capitalize text-left"
                >
                  {sv}
                </button>
              ))}
              <div className="h-px bg-slate-100 mx-2 mt-1" />
            </div>
          )}
          <div className="p-2">
            <div className="flex gap-1.5">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="New…"
                autoFocus={existingSubVariants.length === 0}
                className="flex-1 min-w-0 h-7 px-2 text-sm border border-slate-200 rounded focus:outline-none focus:ring-1 focus:ring-emerald-300 focus:border-emerald-300"
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
