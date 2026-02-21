import { useState, useEffect, useRef } from 'react'
import { Plus, ChevronLeft } from 'lucide-react'
import type { TagData } from '@/types'
import type { ParsedTagVocab } from './types'
import { getTagColor } from './tagColors'

interface TagPickerProps {
  vocab: ParsedTagVocab[]
  existingTags: TagData[]
  onAdd: (tag: TagData) => void
}

export function TagPicker({ vocab, existingTags, onAdd }: TagPickerProps) {
  const [open, setOpen] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSelectedCategory(null)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); setSelectedCategory(null) }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  const existingKeys = new Set(existingTags.map((t) => `${t.category}:${t.value}`))
  const selectedVocab = vocab.find((v) => v.category === selectedCategory)
  const availableValues = selectedVocab
    ? selectedVocab.values.filter((v) => !existingKeys.has(`${selectedCategory}:${v}`))
    : []

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        onClick={() => { setOpen(!open); setSelectedCategory(null) }}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-emerald-300/60 px-2 py-0.5 text-xs text-emerald-600 hover:border-emerald-400 hover:bg-emerald-50 transition-all"
      >
        <Plus className="h-3 w-3" />
        Tag
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 w-[200px] rounded-xl border bg-white shadow-xl shadow-black/5 overflow-hidden">
          {!selectedCategory ? (
            <div className="py-1">
              <div className="px-3 pt-2 pb-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-widest">
                Pick category
              </div>
              {vocab.map((v) => {
                const color = getTagColor(v.category)
                return (
                  <button
                    key={v.category}
                    onClick={() => setSelectedCategory(v.category)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-50 transition-colors text-left group"
                  >
                    <span className={`w-2 h-2 rounded-full ${color.bg} ${color.border} border`} />
                    <span className="capitalize text-slate-700">{v.category}</span>
                    <span className="ml-auto text-xs text-slate-300 group-hover:text-slate-400">{v.values.length}</span>
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="py-1">
              <button
                onClick={() => setSelectedCategory(null)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors w-full"
              >
                <ChevronLeft className="h-3 w-3" />
                <span className="capitalize">{selectedCategory}</span>
              </button>
              <div className="h-px bg-slate-100 mx-2" />
              <div className="max-h-[200px] overflow-y-auto py-1">
                {availableValues.length === 0 ? (
                  <div className="px-3 py-3 text-xs text-slate-400 italic text-center">All values applied</div>
                ) : (
                  availableValues.map((value) => (
                    <button
                      key={value}
                      onClick={() => {
                        onAdd({ category: selectedCategory, value, confidence: 1.0, source: 'manual' })
                        setOpen(false)
                        setSelectedCategory(null)
                      }}
                      className="flex w-full items-center px-3 py-1.5 text-sm text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 transition-colors text-left capitalize"
                    >
                      {value}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
